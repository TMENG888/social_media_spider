import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cloud_log import (FeishuAPI, SyncError, TITLE, block_text, digest, normalized,
                       recognized_body, replace_body, sync, text_blocks)
from report_archive import archive_confirmed, recent_day_content


class FakeAPI:
    def __init__(self, body=""):
        self.lines = [block_text(b) for b in text_blocks(body)]
        self.ids = ["old-" + str(i) for i in range(len(self.lines))]
        self.rev = 1
        self.calls = []
        self.counter = 0
        self.fail_after_append = False
        self.fail_delete = False
        self.edit_after_append = False

    def resolve(self):
        return "test-doc"

    def snapshot(self, doc):
        return {"doc": doc, "revision": self.rev, "ids": self.ids[:],
                "lines": self.lines[:], "body": "\n".join(self.lines)}

    def append(self, snap, children):
        if snap["revision"] != self.rev:
            raise SyncError("revision_conflict")
        self.calls.append(("append", len(children)))
        for block in children:
            self.counter += 1
            self.ids.append("new-" + str(self.counter))
            self.lines.append(block_text(block))
        self.rev += 1
        if self.edit_after_append:
            self.lines[0] += " human material"
        if self.fail_after_append:
            raise SyncError("simulated_response_lost_after_commit")

    def delete(self, snap, start, end):
        if snap["revision"] != self.rev:
            raise SyncError("revision_conflict")
        if self.fail_delete:
            raise SyncError("simulated_delete_failure")
        self.calls.append(("delete", start, end))
        del self.ids[start:end]
        del self.lines[start:end]
        self.rev += 1


class CloudLogTests(unittest.TestCase):
    now = 1792146994

    def archive(self, out, when=None):
        text = "10-16 18:36（北京）\n\n① 关键词进度\n完成 1\n\n② 机器状态\n在线 1\n\n③ 数据质量与效率\n入库 10\n\n④ 异常与下一步\n待重试 1"
        return archive_confirmed(out, {"generatedAt": "2026-10-16T18:36:29+08:00", "sources": {"redis": "ok"}},
                                 {"source": "ok"}, {"text": text}, text, when or self.now)

    def test_pure_render_does_not_touch_output_and_matches_disk(self):
        with tempfile.TemporaryDirectory() as out:
            self.archive(out)
            before = (Path(out) / "cloud-log-body.txt").read_text(encoding="utf-8")
            _, _, body = recent_day_content(out, self.now)
            self.assertEqual(before, body)
            recent_day_content(out, self.now + 10)
            self.assertEqual(before, (Path(out) / "cloud-log-body.txt").read_text(encoding="utf-8"))

    def test_recognition_requires_exact_history_not_just_generated_marker(self):
        with tempfile.TemporaryDirectory() as out:
            self.archive(out)
            body = recent_day_content(out, self.now)[2]
            self.assertTrue(recognized_body(body, out))
            self.assertFalse(recognized_body(body + "\n人工项目计划：不可覆盖", out))
            self.assertFalse(recognized_body(body.replace("入库 10", "入库 999"), out))
            self.assertTrue(recognized_body("", out))

    def test_full_sync_reads_back_all_values_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as out:
            entry = self.archive(out)
            api = FakeAPI()
            result = sync(out, api, now=self.now)
            self.assertTrue(result["cloudConfirmed"])
            self.assertIn(json.loads(entry.read_text(encoding="utf-8"))["reportId"], result["reportIds"])
            calls = api.calls[:]
            self.assertTrue(sync(out, api, now=self.now)["cloudConfirmed"])
            self.assertEqual(api.calls, calls)

    def test_old_recognized_body_is_backed_up_before_replacement(self):
        with tempfile.TemporaryDirectory() as out:
            self.archive(out)
            old = recent_day_content(out, self.now)[2]
            api = FakeAPI(old)
            result = sync(out, api, now=self.now + 10)
            self.assertTrue(result["cloudConfirmed"])
            backup = list((Path(out) / "cloud-sync").glob("backup-*.json"))
            self.assertEqual(len(backup), 1)
            self.assertEqual(normalized(json.loads(backup[0].read_text(encoding="utf-8"))["oldBody"]), normalized(old))
            self.assertEqual(api.calls[-1][0], "delete")

    def test_manual_material_blocks_all_writes(self):
        with tempfile.TemporaryDirectory() as out:
            self.archive(out)
            api = FakeAPI("重要人工工作文档")
            with self.assertRaisesRegex(SyncError, "manual_body_stop"):
                sync(out, api, now=self.now)
            self.assertEqual(api.calls, [])

    def test_check_never_writes_cloud_or_claims_sync(self):
        with tempfile.TemporaryDirectory() as out:
            self.archive(out)
            api = FakeAPI()
            result = sync(out, api, check_only=True, now=self.now)
            self.assertEqual(result["status"], "preflight_ok")
            self.assertFalse(result["cloudConfirmed"])
            self.assertEqual(api.calls, [])

    def test_empty_or_bad_local_history_cannot_clear_cloud(self):
        with tempfile.TemporaryDirectory() as out:
            api = FakeAPI("existing body")
            with self.assertRaisesRegex(SyncError, "no_recent"):
                sync(out, api, now=self.now)
            self.assertEqual(api.calls, [])
            self.archive(out)
            entry = next((Path(out) / "report-history").glob("*/*.json"))
            record = json.loads(entry.read_text(encoding="utf-8"))
            record["text"] = "invalid"
            entry.write_text(json.dumps(record), encoding="utf-8")
            with self.assertRaisesRegex(SyncError, "sections_invalid"):
                sync(out, api, now=self.now)
            self.assertEqual(api.calls, [])

    def test_commit_then_lost_response_recovers_without_duplicate_report(self):
        with tempfile.TemporaryDirectory() as out:
            self.archive(out)
            old = recent_day_content(out, self.now)[2]
            api = FakeAPI(old)
            api.fail_after_append = True
            with self.assertRaisesRegex(SyncError, "response_lost"):
                sync(out, api, now=self.now + 10)
            self.assertTrue((Path(out) / "cloud-sync" / "pending.json").exists())
            api.fail_after_append = False
            self.assertTrue(sync(out, api, now=self.now + 10)["cloudConfirmed"])
            expected = recent_day_content(out, self.now + 10)[2]
            self.assertEqual(normalized("\n".join(api.lines)), normalized(expected))
            self.assertFalse((Path(out) / "cloud-sync" / "pending.json").exists())

    def test_delete_failure_preserves_old_body_and_next_run_recovers(self):
        with tempfile.TemporaryDirectory() as out:
            self.archive(out)
            old = recent_day_content(out, self.now)[2]
            api = FakeAPI(old)
            api.fail_delete = True
            with self.assertRaisesRegex(SyncError, "delete_failure"):
                sync(out, api, now=self.now + 10)
            self.assertTrue(normalized("\n".join(api.lines)).startswith(normalized(old)))
            api.fail_delete = False
            self.assertTrue(sync(out, api, now=self.now + 11)["cloudConfirmed"])

    def test_concurrent_manual_change_stops_cleanup_and_recovery(self):
        with tempfile.TemporaryDirectory() as out:
            self.archive(out)
            old = recent_day_content(out, self.now)[2]
            api = FakeAPI(old)
            api.edit_after_append = True
            with self.assertRaisesRegex(SyncError, "readback_mismatch"):
                sync(out, api, now=self.now + 10)
            self.assertFalse(any(c[0] == "delete" for c in api.calls))
            api.edit_after_append = False
            with self.assertRaisesRegex(SyncError, "pending_body_changed"):
                sync(out, api, now=self.now + 10)

    def test_non_text_or_links_are_not_silently_flattened(self):
        for block in ({"block_type": 27}, {"block_type": 2, "children": ["child"]},
                      {"block_type": 2, "text": {"elements": [{"mention_doc": {}}]}},
                      {"block_type": 2, "text": {"elements": [{"text_run": {
                          "content": "link", "text_element_style": {"link": {"url": "https://example.com"}}}}]}}):
            with self.assertRaises(SyncError):
                block_text(block)

    def test_old_verified_body_does_not_permit_a_new_manual_edit(self):
        with tempfile.TemporaryDirectory() as out:
            self.archive(out)
            api = FakeAPI()
            sync(out, api, now=self.now)
            api.lines.append("manual note")
            api.ids.append("human-id")
            api.rev += 1
            before = api.calls[:]
            with self.assertRaisesRegex(SyncError, "manual_body_stop"):
                sync(out, api, now=self.now + 10)
            self.assertEqual(api.calls, before)

    def test_append_batches_at_most_50(self):
        with tempfile.TemporaryDirectory() as out:
            api = FakeAPI()
            desired = "\n".join("line " + str(i) for i in range(123))
            replace_body(api, "test-doc", out, desired)
            self.assertEqual([c[1] for c in api.calls if c[0] == "append"], [50, 50, 23])

    def test_resolve_rejects_wrong_title_or_non_docx(self):
        for node in ({"title": "another document", "obj_type": "docx", "obj_token": "x"},
                     {"title": TITLE, "obj_type": "sheet", "obj_token": "x"}):
            api = object.__new__(FeishuAPI)
            api.request = lambda *a: {"data": {"node": node}}
            with self.assertRaisesRegex(SyncError, "title_mismatch"):
                api.resolve()


if __name__ == "__main__":
    unittest.main()
