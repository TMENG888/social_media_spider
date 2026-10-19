"""Mirror acknowledged local reports to ONE wiki document; no crawler operations.

All requests use the official host. No cookies, webhook credentials, or raw API
errors are logged. Writes use document revision guards and preserve a backup.
"""
import argparse
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from collect import atomic_json
from report_archive import BEIJING, recent_day_content, render_recent_day

# Public source never embeds a deployment's document or tenant identifiers.
_target_file = Path(__file__).resolve().parent / "cloud-log-target.json"
TARGET_CONFIG = json.loads(_target_file.read_text(encoding="utf-8-sig")) if _target_file.exists() else {}
TARGET_URL = os.environ.get("FEISHU_LOG_TARGET_URL") or TARGET_CONFIG.get("target_url") or "https://example.feishu.cn/wiki/EXAMPLE_LOG_DOCUMENT"
NODE = urllib.parse.urlparse(TARGET_URL).path.rsplit("/", 1)[-1]
TITLE = "飞书机器人日报日志（最近24小时）"
API = "https://open.feishu.cn/open-apis"
TEXT_TYPES = {2: "text", 3: "heading1", 4: "heading2", 5: "heading3",
              6: "heading4", 7: "heading5", 8: "heading6", 9: "heading7",
              10: "heading8", 11: "heading9"}


class SyncError(Exception):
    """Only safe fixed error labels (and numeric API codes) go to disk/stdout."""


def validate_cloud_target():
    if (not re.fullmatch(r"https://[A-Za-z0-9-]+\.feishu\.cn/wiki/[A-Za-z0-9_-]+", TARGET_URL)
            or NODE == "EXAMPLE_LOG_DOCUMENT"):
        raise SyncError("cloud_target_missing_or_invalid")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise SyncError("api_redirect_refused")


class FeishuAPI:
    def __init__(self, app_id, secret):
        self.token = None
        self.opener = urllib.request.build_opener(NoRedirect())
        result = self.request("POST", "/auth/v3/tenant_access_token/internal",
                              {"app_id": app_id, "app_secret": secret})
        self.token = result.get("tenant_access_token")
        if not self.token:
            raise SyncError("tenant_token_missing")

    def request(self, method, path, data=None):
        if not path.startswith("/") or ".." in path or "://" in path:
            raise SyncError("invalid_api_path")
        headers = {"Content-Type": "application/json; charset=utf-8"}
        if self.token:
            headers["Authorization"] = "Bearer " + self.token
        request = urllib.request.Request(API + path,
            None if data is None else json.dumps(data, ensure_ascii=False).encode(),
            headers, method=method)
        try:
            with self.opener.open(request, timeout=30) as response:
                result = json.load(response)
        except urllib.error.HTTPError as exc:
            raise SyncError("api_http_" + str(exc.code)) from None
        except SyncError:
            raise
        except Exception:
            raise SyncError("api_network_or_invalid_response") from None
        code = result.get("code")
        if code != 0:
            raise SyncError("api_code_" + (str(code) if isinstance(code, int) else "unknown"))
        return result

    def resolve(self):
        node = self.request("GET", "/wiki/v2/spaces/get_node?token=" + NODE)["data"]["node"]
        if node.get("obj_type") != "docx" or node.get("title") != TITLE:
            raise SyncError("target_type_or_title_mismatch")
        doc = node.get("obj_token", "")
        if not re.fullmatch(r"[A-Za-z0-9_-]+", doc):
            raise SyncError("invalid_document_id")
        return doc

    def snapshot(self, doc):
        for _ in range(3):
            before = self.request("GET", f"/docx/v1/documents/{doc}")["data"]["document"]
            if before.get("title") != TITLE:
                raise SyncError("document_title_changed")
            blocks, page = [], ""
            for _ in range(100):
                query = "?page_size=500" + ("&page_token=" + urllib.parse.quote(page, safe="") if page else "")
                data = self.request("GET", f"/docx/v1/documents/{doc}/blocks" + query)["data"]
                blocks.extend(data.get("items", []))
                if not data.get("has_more"):
                    break
                next_page = data.get("page_token")
                if not next_page or next_page == page:
                    raise SyncError("invalid_blocks_pagination")
                page = next_page
            else:
                raise SyncError("document_too_large")
            after = self.request("GET", f"/docx/v1/documents/{doc}")["data"]["document"]
            if before.get("revision_id") != after.get("revision_id"):
                continue
            if after.get("title") != TITLE:
                raise SyncError("document_title_changed")
            revision = after.get("revision_id")
            if not isinstance(revision, int) or revision < 0:
                raise SyncError("document_revision_missing")
            roots = [b for b in blocks if b.get("block_id") == doc and b.get("block_type") == 1]
            if len(roots) != 1:
                raise SyncError("document_root_missing")
            child_ids = roots[0].get("children", [])
            index = {b["block_id"]: b for b in blocks}
            if len(index) != len(blocks) or set(index) != {doc, *child_ids}:
                raise SyncError("nested_or_unknown_material_stop")
            children = [index[b] for b in child_ids]
            lines = [block_text(b) for b in children]
            return {"doc": doc, "revision": revision, "ids": child_ids,
                    "lines": lines, "body": "\n".join(lines)}
        raise SyncError("document_changed_during_read")

    def append(self, snap, children):
        doc, rev = snap["doc"], snap["revision"]
        self.request("POST", f"/docx/v1/documents/{doc}/blocks/{doc}/children?document_revision_id={rev}",
                     {"children": children, "index": len(snap["ids"])})

    def delete(self, snap, start, end):
        doc, rev = snap["doc"], snap["revision"]
        self.request("DELETE", f"/docx/v1/documents/{doc}/blocks/{doc}/children/batch_delete?document_revision_id={rev}",
                     {"start_index": start, "end_index": end})


def block_text(block):
    name = TEXT_TYPES.get(block.get("block_type"))
    if not name or block.get("children"):
        raise SyncError("non_generated_material_stop")
    values = []
    for element in block.get(name, {}).get("elements", []):
        # Do not flatten mentions, links, equations, files, images, or synced blocks.
        if set(element) != {"text_run"}:
            raise SyncError("non_text_material_stop")
        run = element["text_run"]
        if run.get("text_element_style", {}).get("link"):
            raise SyncError("linked_material_stop")
        values.append(run.get("content", ""))
    return "".join(values)


def normalized(text):
    return "\n".join(re.sub(r"^#{1,6} ", "", line).strip()
                     for line in text.splitlines() if line.strip())


def digest(text):
    return hashlib.sha256(normalized(text).encode()).hexdigest()


def recognized_body(body, out):
    """Never accept a mere 'generated' marker: require exact archived evidence."""
    if not normalized(body):
        return True
    matches = re.findall(r"^窗口截至：(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)（北京时间）$", body, re.M)
    if len(matches) != 1:
        return False
    when = datetime.strptime(matches[0], "%Y-%m-%d %H:%M:%S").replace(tzinfo=BEIJING).timestamp()
    _, _, expected = recent_day_content(out, when)
    return normalized(body) == normalized(expected)


def text_blocks(body):
    result = []
    for line in body.splitlines():
        if not line.strip():
            continue
        is_heading = line.startswith("## ")
        content = line[3:] if is_heading else line
        if len(content.encode("utf-8")) > 12000:
            raise SyncError("generated_line_too_long")
        name, kind = ("heading2", 4) if is_heading else ("text", 2)
        result.append({"block_type": kind, name: {"elements": [{"text_run": {"content": content}}]}})
    if len(result) > 2000:
        raise SyncError("generated_body_too_large")
    return result


def replace_body(api, doc, out, desired):
    """Append verified new text before removing old text. Crash recovery is exact."""
    folder = Path(out) / "cloud-sync"
    folder.mkdir(parents=True, exist_ok=True)
    pending = folder / "pending.json"
    snap = api.snapshot(doc)
    if pending.exists():
        prior = json.loads(pending.read_text(encoding="utf-8"))
        if prior.get("doc") != doc:
            raise SyncError("pending_target_mismatch")
        old_ids, old_body, wanted = prior["oldIds"], prior["oldBody"], prior["desiredBody"]
        n = len(old_ids)
        if normalized(snap["body"]) == normalized(wanted):
            pending.unlink()
        elif (snap["ids"][:n] == old_ids and
              normalized("\n".join(snap["lines"][:n])) == normalized(old_body)):
            tail = snap["lines"][n:]
            expected = [block_text(b) for b in text_blocks(wanted)]
            if tail != expected[:len(tail)]:
                raise SyncError("pending_body_changed_stop")
            if tail:
                api.delete(snap, n, len(snap["ids"]))
                snap = api.snapshot(doc)
            if snap["ids"] != old_ids or normalized(snap["body"]) != normalized(old_body):
                raise SyncError("pending_rollback_not_verified")
            pending.unlink()
        else:
            raise SyncError("pending_body_changed_stop")
        snap = api.snapshot(doc)
    if normalized(snap["body"]) == normalized(desired):
        return snap
    verified = folder / "verified-body.json"
    previous = json.loads(verified.read_text(encoding="utf-8")) if verified.exists() else {}
    previous_match = previous.get("doc") == doc and previous.get("bodySha256") == digest(snap["body"])
    if not previous_match and not recognized_body(snap["body"], out):
        raise SyncError("unrecognized_or_manual_body_stop")
    children = text_blocks(desired)
    transaction = {"doc": doc, "oldIds": snap["ids"], "oldBody": snap["body"],
                   "desiredBody": desired, "startedAt": time.time()}
    atomic_json(folder / ("backup-" + str(time.time_ns()) + ".json"), transaction)
    atomic_json(pending, transaction)
    original_ids, original_lines = snap["ids"][:], snap["lines"][:]
    new_lines = []
    for offset in range(0, len(children), 50):
        batch = children[offset:offset + 50]
        api.append(snap, batch)
        new_lines.extend(block_text(b) for b in batch)
        snap = api.snapshot(doc)
        if snap["ids"][:len(original_ids)] != original_ids or snap["lines"] != original_lines + new_lines:
            raise SyncError("appended_body_readback_mismatch")
    if original_ids:
        api.delete(snap, 0, len(original_ids))
    final = api.snapshot(doc)
    if normalized(final["body"]) != normalized(desired):
        raise SyncError("final_body_readback_mismatch")
    atomic_json(verified, {"doc": doc, "bodySha256": digest(desired), "verifiedAt": time.time()})
    pending.unlink()
    return final


def sync(out, api, check_only=False, now=None):
    now = int(time.time()) if now is None else now
    entries = render_recent_day(out, now)
    body = (Path(out) / "cloud-log-body.txt").read_text(encoding="utf-8")
    # Do not manufacture reports or erase a valid cloud history with an empty local one.
    if not entries:
        raise SyncError("no_recent_confirmed_local_reports")
    for entry in entries:
        for title in ("① 关键词进度", "② 机器状态", "③ 数据质量与效率", "④ 异常与下一步"):
            if entry["text"].count(title) != 1:
                raise SyncError("local_report_sections_invalid")
    doc = api.resolve()
    if check_only:
        snap = api.snapshot(doc)
        if not recognized_body(snap["body"], out):
            verified = Path(out) / "cloud-sync" / "verified-body.json"
            previous = json.loads(verified.read_text(encoding="utf-8")) if verified.exists() else {}
            if previous.get("doc") != doc or previous.get("bodySha256") != digest(snap["body"]):
                raise SyncError("unrecognized_or_manual_body_stop")
        return {"status": "preflight_ok", "cloudConfirmed": False, "reportIds": [e["reportId"] for e in entries]}
    final = replace_body(api, doc, out, body)
    # A fresh read verifies title, window, IDs, timestamps and all four section values together.
    fresh = api.snapshot(doc)
    if normalized(fresh["body"]) != normalized(body) or fresh["revision"] != final["revision"]:
        raise SyncError("fresh_readback_mismatch")
    return {"status": "success", "cloudConfirmed": True, "bodySha256": digest(body),
            "documentRevision": fresh["revision"], "reportIds": [e["reportId"] for e in entries],
            "windowUntil": datetime.fromtimestamp(now, BEIJING).isoformat()}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="Read-only API/title/body preflight; no cloud writes")
    args = parser.parse_args()
    out = Path(__file__).resolve().parent / "output"
    result = {"status": "failed", "cloudConfirmed": False, "targetUrl": TARGET_URL,
              "startedAt": datetime.now().astimezone().isoformat()}
    code = 1
    try:
        validate_cloud_target()
        app_id = os.environ.get("FEISHU_DOC_APP_ID", "")
        secret = os.environ.get("FEISHU_DOC_APP_SECRET", "")
        if not app_id or not secret:
            raise SyncError("app_credentials_missing")
        result.update(sync(out, FeishuAPI(app_id, secret), args.check))
        code = 0
    except SyncError as exc:
        result["error"] = str(exc)
    except Exception:
        result["error"] = "unexpected_sync_failure"
    result["finishedAt"] = datetime.now().astimezone().isoformat()
    atomic_json(out / "cloud-sync" / "latest-run.json", result)
    print("Cloud log sync confirmed" if result["cloudConfirmed"] else
          "Cloud log preflight verified" if code == 0 else "Cloud log sync NOT confirmed: " + result["error"])
    return code


if __name__ == "__main__":
    sys.exit(main())
