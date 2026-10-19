"""Dedicated docx mirror via official CLI; credentials stay inside lark-cli."""
import argparse
import html
import json
import os
import re
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from collect import atomic_json
from cloud_log import TARGET_URL, TARGET_CONFIG, TITLE, SyncError, digest, normalized, validate_cloud_target
from report_archive import BEIJING, recent_day_content, render_recent_day

ROOT = Path(__file__).resolve().parent
METRIC_DOC = os.environ.get("FEISHU_METRIC_DOC_ID") or TARGET_CONFIG.get("metric_doc_id") or "EXAMPLE_METRIC_DOCUMENT"
METRIC_TITLE = "打标监测指标体系与证据规范"
METRIC_PLACEHOLDER = "指标规范：请参阅部署方的团队指标规范文档"
METRIC_CITE = '<cite doc-id="' + METRIC_DOC + '" file-type="wiki" title="' + METRIC_TITLE + '" type="doc"></cite>'
SECTIONS = ("① 关键词进度", "② 机器状态", "③ 数据质量与效率", "④ 异常与下一步")


class Runner:
    def __init__(self, executable, profile):
        self.executable = executable
        self.profile = profile

    def call(self, arguments, content=None):
        # No shell, no credentials in argv, no raw stdout/stderr logs.
        env = dict(os.environ, LARKSUITE_CLI_NO_UPDATE_NOTIFIER="1", LARKSUITE_CLI_NO_SKILLS_NOTIFIER="1")
        try:
            process = subprocess.run([self.executable, "--profile", self.profile] + arguments,
                input=content, capture_output=True, encoding="utf-8", errors="strict",
                timeout=90, env=env, cwd=str(ROOT),
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            response = json.loads(process.stdout if process.returncode == 0 else process.stderr)
        except subprocess.TimeoutExpired:
            raise SyncError("cli_timeout_result_unknown") from None
        except Exception:
            raise SyncError("cli_runtime_or_json_failure") from None
        if process.returncode == 10:
            raise SyncError("cli_confirmation_required_no_bypass")
        if process.returncode != 0 or response.get("ok") is not True:
            error = response.get("error", {})
            kind = error.get("subtype", "failure")
            if not re.fullmatch(r"[A-Za-z0-9_-]+", str(kind)):
                kind = "failure"
            code = error.get("code")
            label = "cli_" + kind + ("_" + str(code) if isinstance(code, int) else "")
            raise SyncError(label)
        if response.get("identity") != "user":
            raise SyncError("cli_identity_mismatch")
        return response

    def fetch(self):
        result = self.call(["docs", "+fetch", "--doc", TARGET_URL, "--detail", "full", "--as", "user"])
        doc = result["data"]["document"]
        # Full fetch is retained intact so citation/reference context is not discarded.
        snap = parse_document(doc)
        snap["response"] = result
        return snap

    def update_args(self, snap):
        args = ["docs", "+update", "--doc", TARGET_URL, "--as", "user",
                "--doc-format", "xml", "--content", "-", "--revision-id", str(snap["revision"])]
        if snap["ids"]:
            args += ["--command", "block_replace", "--start-block-id", snap["ids"][0],
                     "--end-block-id", snap["ids"][-1]]
        else:
            args += ["--command", "append"]
        return args

    def preview(self, snap, content):
        response = self.call(self.update_args(snap) + ["--dry-run"], content)
        if response.get("dry_run") is not True:
            raise SyncError("cli_dry_run_not_confirmed")

    def write(self, snap, content):
        response = self.call(self.update_args(snap), content)
        data = response.get("data", {})
        if data.get("result") != "success" or data.get("warnings"):
            raise SyncError("cli_write_partial_or_warning_readback_required")


def inline_text(element):
    allowed = {"b", "em", "u", "del", "span", "br"}
    text = element.text or ""
    for child in element:
        if child.tag == "cite":
            expected = {"doc-id": METRIC_DOC, "file-type": "wiki", "title": METRIC_TITLE, "type": "doc"}
            if child.attrib != expected or list(child) or (child.text or "").strip():
                raise SyncError("unknown_citation_or_manual_material_stop")
            text += "请参阅部署方的团队指标规范文档"
        elif child.tag in allowed:
            if child.attrib or (child.tag == "br" and list(child)):
                raise SyncError("unknown_inline_material_stop")
            text += "\n" if child.tag == "br" else inline_text(child)
        else:
            raise SyncError("non_generated_material_stop")
        text += child.tail or ""
    return text


def parse_document(doc):
    raw = doc.get("content", "")
    if "<!" in raw or "<?" in raw:
        raise SyncError("unsafe_xml_stop")
    try:
        root = ET.fromstring("<root>" + raw + "</root>")
    except ET.ParseError:
        raise SyncError("document_xml_invalid") from None
    if (root.text or "").strip() or not len(root) or root[0].tag != "title":
        raise SyncError("document_title_missing")
    if inline_text(root[0]) != TITLE or any(b.tag == "title" for b in list(root)[1:]):
        raise SyncError("document_title_mismatch")
    if root[0].get("id") != doc.get("document_id"):
        raise SyncError("document_identity_mismatch")
    revision = doc.get("revision_id")
    if not isinstance(revision, int) or revision < 0:
        raise SyncError("document_revision_missing")
    if doc.get("tips"):
        raise SyncError("document_read_degraded_stop")
    if doc.get("reference_map"):
        # Comments/unknown resources may contain important user material.
        raise SyncError("document_comments_or_sidecar_stop")
    ids, lines, tags = [], [], []
    cite_count = 0
    for block in list(root)[1:]:
        if block.tag not in {"p", "h1", "h2", "h3", "h4", "h5", "h6"}:
            raise SyncError("non_generated_material_stop")
        if set(block.attrib) - {"id"} or not block.get("id"):
            raise SyncError("block_structure_unrecognized")
        if (block.tail or "").strip():
            raise SyncError("unattached_manual_text_stop")
        line = inline_text(block)
        citations = list(block.iter("cite"))
        if citations and (len(citations) != 1 or line != METRIC_PLACEHOLDER or block.tag != "p"):
            raise SyncError("citation_location_unrecognized")
        cite_count += len(citations)
        ids.append(block.get("id")); lines.append(line); tags.append(block.tag)
    if len(set(ids)) != len(ids) or cite_count > 1:
        raise SyncError("duplicate_blocks_or_citations_stop")
    return {"doc": doc["document_id"], "revision": revision, "ids": ids,
            "lines": lines, "tags": tags, "body": "\n".join(lines),
            "xml": raw, "metricCite": bool(cite_count)}


def recognized(snap, out):
    """Recognize current or observed legacy template using actual archived reports."""
    if not normalized(snap["body"]):
        return True
    windows = re.findall(r"^窗口截至：(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)（北京时间）$", snap["body"], re.M)
    if len(windows) != 1:
        return False
    when = datetime.strptime(windows[0], "%Y-%m-%d %H:%M:%S").replace(tzinfo=BEIJING).timestamp()
    entries, _, expected = recent_day_content(out, when)
    if normalized(expected) == normalized(snap["body"]):
        return True
    # The 2026-10-13 renderer used these exact two deployment-specific header lines.
    legacy = expected.replace("本程序不创建或启用定时任务；发送时间由部署方自行安排。",
                              "固定日报：北京时间09:00、14:00、18:00；5分钟loop已暂停。")
    legacy = legacy.replace("仅保留实际归档记录，不补造历史。历史不完整时不能计算完整日变化。",
                            "归档自2026-10-13启用；此前未保存的报告不补造。历史不完整时不能计算完整日变化。")
    return bool(entries) and normalized(legacy) == normalized(snap["body"])


def body_xml(body, keep_cite):
    blocks = []
    for line in body.splitlines():
        if not line.strip():
            continue
        if line == METRIC_PLACEHOLDER and keep_cite:
            blocks.append("<p>指标规范：" + METRIC_CITE + "</p>")
        else:
            tag = "h2" if line.startswith("## ") else "p"
            text = line[3:] if tag == "h2" else line
            blocks.append("<" + tag + ">" + html.escape(text, quote=False) + "</" + tag + ">")
    return "".join(blocks)


def synchronize(out, runner, check=False, now=None):
    now = int(time.time()) if now is None else now
    entries = render_recent_day(out, now)
    if not entries:
        raise SyncError("no_recent_confirmed_local_reports")
    for entry in entries:
        if any(entry["text"].count(section) != 1 for section in SECTIONS):
            raise SyncError("local_report_sections_invalid")
    desired = (Path(out) / "cloud-log-body.txt").read_text(encoding="utf-8")
    folder = Path(out) / "cloud-sync"
    folder.mkdir(parents=True, exist_ok=True)
    snap = runner.fetch()
    verified_path = folder / "cli-verified.json"
    prior = json.loads(verified_path.read_text(encoding="utf-8")) if verified_path.exists() else {}
    is_verified = (prior.get("doc") == snap["doc"] and prior.get("bodySha256") == digest(snap["body"])
                   and prior.get("metricCite") == snap["metricCite"])
    if not is_verified and not recognized(snap, out):
        raise SyncError("unrecognized_or_manual_body_stop")
    xml = body_xml(desired, snap["metricCite"])
    if check:
        runner.preview(snap, xml)
        return {"status": "preflight_ok", "cloudConfirmed": False, "documentRevision": snap["revision"],
                "reportIds": [e["reportId"] for e in entries]}
    if normalized(snap["body"]) != normalized(desired):
        transaction = {"startedAt": datetime.now().astimezone().isoformat(), "before": snap,
                       "desiredBody": desired, "desiredXml": xml}
        atomic_json(folder / ("cli-backup-" + str(time.time_ns()) + ".json"), transaction)
        runner.preview(snap, xml)
        before = runner.fetch()
        if before != snap:
            raise SyncError("document_changed_before_write_stop")
        runner.write(snap, xml)
    final = runner.fetch()
    if (final["doc"] != snap["doc"] or normalized(final["body"]) != normalized(desired)
            or final["metricCite"] != snap["metricCite"]):
        raise SyncError("final_body_or_citation_readback_mismatch")
    fresh = runner.fetch()
    if fresh != final:
        raise SyncError("document_changed_during_readback")
    atomic_json(verified_path, {"doc": final["doc"], "bodySha256": digest(desired),
                             "metricCite": final["metricCite"], "verifiedAt": time.time()})
    return {"status": "success", "cloudConfirmed": True, "bodySha256": digest(desired),
            "documentRevision": final["revision"], "reportIds": [e["reportId"] for e in entries],
            "metricLinkPreserved": final["metricCite"],
            "windowUntil": datetime.fromtimestamp(now, BEIJING).isoformat()}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    result = {"status": "failed", "cloudConfirmed": False, "backend": "lark-cli",
              "targetUrl": TARGET_URL, "startedAt": datetime.now().astimezone().isoformat()}
    code = 1
    try:
        validate_cloud_target()
        config = json.loads((ROOT / "cloud-log-cli.json").read_text(encoding="utf-8"))
        executable = Path(config["executable"])
        if not executable.is_absolute() or executable.name != "lark-cli.exe" or not executable.is_file():
            raise SyncError("cli_binary_missing_or_invalid")
        if config.get("profile") != "social-media-log":
            raise SyncError("cli_profile_mismatch")
        result.update(synchronize(ROOT / "output", Runner(str(executable), config["profile"]), args.check))
        code = 0
    except SyncError as exc:
        result["error"] = str(exc)
    except Exception:
        result["error"] = "unexpected_cli_sync_failure"
    result["finishedAt"] = datetime.now().astimezone().isoformat()
    atomic_json(ROOT / "output" / "cloud-sync" / "latest-run.json", result)
    print("Cloud log sync confirmed" if result["cloudConfirmed"] else
          "Cloud log preflight verified" if code == 0 else "Cloud log sync NOT confirmed: " + result["error"])
    return code


if __name__ == "__main__":
    sys.exit(main())
