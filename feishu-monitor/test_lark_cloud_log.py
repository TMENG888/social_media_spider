import copy
import json
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch

from cloud_log import SyncError, TITLE, normalized
from lark_cloud_log import (METRIC_CITE, METRIC_PLACEHOLDER, Runner, body_xml,
                           parse_document, recognized, synchronize)
from report_archive import archive_confirmed, recent_day_content


def document(body, revision=8):
    root = ET.fromstring("<root>" + body + "</root>")
    for i, child in enumerate(root):
        child.set("id", "block-" + str(i) + "-v" + str(revision))
    content = '<title id="testdoc">' + TITLE + '</title>' + "".join(ET.tostring(b, encoding="unicode") for b in root)
    return {"document_id": "testdoc", "revision_id": revision, "content": content}


class FakeRunner:
    def __init__(self, body):
        self.doc = document(body)
        self.calls = []
        self.change_before_write = False

    def fetch(self):
        return parse_document(self.doc)

    def preview(self, snap, content):
        self.calls.append("preview")
        if self.change_before_write:
            self.doc["revision_id"] += 1

    def write(self, snap, content):
        self.calls.append("write")
        if snap["revision"] != self.doc["revision_id"]:
            raise SyncError("revision_conflict")
        self.doc = document(content, snap["revision"] + 1)


class CLILogTests(unittest.TestCase):
    now = 1792146994

    def archive(self, out):
        text = "10-16 18:36（北京）\n\n① 关键词进度\n完成✅ 1\n\n② 机器状态\n在线 1\n\n③ 数据质量与效率\n入库 10\n\n④ 异常与下一步\n重试 1"
        archive_confirmed(out, {"generatedAt": "2026-10-16T18:36:29+08:00", "sources": {"redis": "ok"}},
                          {"source": "ok"}, {"card": text}, text, self.now)
        return recent_day_content(out, self.now)[2]

    def test_realistic_legacy_template_requires_exact_archived_reports(self):
        with tempfile.TemporaryDirectory() as out:
            body = self.archive(out)
            legacy = body.replace("本程序不创建或启用定时任务；发送时间由部署方自行安排。",
                                  "固定日报：北京时间09:00、14:00、18:00；5分钟loop已暂停。")
            legacy = legacy.replace("仅保留实际归档记录，不补造历史。历史不完整时不能计算完整日变化。",
                                    "归档自2026-10-13启用；此前未保存的报告不补造。历史不完整时不能计算完整日变化。")
            runner = FakeRunner(body_xml(legacy, True))
            self.assertTrue(recognized(runner.fetch(), out))
            runner.doc = document(body_xml(legacy + "\n重要工作计划", True))
            self.assertFalse(recognized(runner.fetch(), out))

    def test_sync_retains_title_and_metric_citation_and_every_report_value(self):
        with tempfile.TemporaryDirectory() as out:
            body = self.archive(out)
            runner = FakeRunner(body_xml(body, True))
            result = synchronize(out, runner, now=self.now + 10)
            self.assertTrue(result["cloudConfirmed"])
            self.assertTrue(result["metricLinkPreserved"])
            self.assertEqual(runner.fetch()["revision"], 9)
            self.assertEqual(normalized(runner.fetch()["body"]), normalized(recent_day_content(out, self.now + 10)[2]))
            self.assertIn('doc-id="EXAMPLE_METRIC_DOCUMENT"', runner.doc["content"])

    def test_idempotency_does_not_rewrite_cloud(self):
        with tempfile.TemporaryDirectory() as out:
            body = self.archive(out)
            runner = FakeRunner(body_xml(body, True))
            self.assertTrue(synchronize(out, runner, now=self.now)["cloudConfirmed"])
            self.assertEqual(runner.calls, [])

    def test_preview_does_not_claim_write_or_modify_cloud(self):
        with tempfile.TemporaryDirectory() as out:
            body = self.archive(out)
            runner = FakeRunner(body_xml(body, True))
            before = copy.deepcopy(runner.doc)
            result = synchronize(out, runner, check=True, now=self.now + 10)
            self.assertFalse(result["cloudConfirmed"])
            self.assertEqual(runner.doc, before)
            self.assertEqual(runner.calls, ["preview"])

    def test_manual_material_stops_before_even_write_preview(self):
        with tempfile.TemporaryDirectory() as out:
            body = self.archive(out)
            runner = FakeRunner(body_xml(body, True) + "<p>人工工作计划</p>")
            with self.assertRaisesRegex(SyncError, "manual_body_stop"):
                synchronize(out, runner, now=self.now + 10)
            self.assertEqual(runner.calls, [])

    def test_missing_history_does_not_erase_old_cloud_reports(self):
        with tempfile.TemporaryDirectory() as out:
            runner = FakeRunner("<p>existing</p>")
            with self.assertRaisesRegex(SyncError, "no_recent"):
                synchronize(out, runner, now=self.now)
            self.assertEqual(runner.calls, [])

    def test_concurrent_revision_change_stops_before_mutation(self):
        with tempfile.TemporaryDirectory() as out:
            body = self.archive(out)
            runner = FakeRunner(body_xml(body, True))
            runner.change_before_write = True
            with self.assertRaisesRegex(SyncError, "changed_before_write"):
                synchronize(out, runner, now=self.now + 10)
            self.assertNotIn("write", runner.calls)

    def test_unsafe_or_unknown_resources_not_flattened(self):
        for xml in ("<p><cite doc-id=\"unknown\"/></p>", "<p><a href=\"https://example.com\">important</a></p>",
                    "<img token=\"resource\"/>", "<table><tr/></table>", "<p><span color=\"red\">note</span></p>"):
            with self.subTest(xml=xml), self.assertRaises(SyncError):
                parse_document(document(xml))

    def test_citation_only_allowed_in_exact_generated_header(self):
        for xml in ("<p>人工作业" + METRIC_CITE + "</p>",
                    "<p>指标规范：" + METRIC_CITE + "</p><p>指标规范：" + METRIC_CITE + "</p>"):
            with self.assertRaises(SyncError):
                parse_document(document(xml))

    def test_title_comments_and_degraded_reads_stop(self):
        doc = document("<p>body</p>")
        for changed in ({**doc, "content": doc["content"].replace(TITLE, "different")},
                        {**doc, "reference_map": {"comments": {"x": "important"}}},
                        {**doc, "tips": "degraded"}):
            with self.assertRaises(SyncError):
                parse_document(changed)

    def test_xml_escapes_data_not_markup(self):
        body = body_xml("a < b & c > d\n" + METRIC_PLACEHOLDER, True)
        self.assertIn("a &lt; b &amp; c &gt; d", body)
        self.assertIn(METRIC_CITE, body)
        self.assertEqual(parse_document(document(body))["body"], "a < b & c > d\n" + METRIC_PLACEHOLDER)

    @patch("lark_cloud_log.subprocess.run")
    def test_cli_json_contract_no_secret_or_shell_in_argv(self, run):
        run.return_value = subprocess.CompletedProcess([], 0, '{"ok":true,"identity":"user","data":{}}', '')
        result = Runner("lark-cli.exe", "social-media-log").call(["docs", "+update"], "private report")
        self.assertTrue(result["ok"])
        argv, kwargs = run.call_args.args[0], run.call_args.kwargs
        self.assertNotIn("private report", argv)
        self.assertEqual(kwargs["input"], "private report")
        self.assertNotIn("shell", kwargs)
        self.assertEqual(argv[:3], ["lark-cli.exe", "--profile", "social-media-log"])

    @patch("lark_cloud_log.subprocess.run")
    def test_error_output_sanitized_and_confirmation_not_bypassed(self, run):
        runner = Runner("lark-cli.exe", "social-media-log")
        run.return_value = subprocess.CompletedProcess([], 1, '', json.dumps({"error": {
            "subtype": "token_missing", "message": "secret should not appear"}}))
        with self.assertRaisesRegex(SyncError, "^cli_token_missing$"):
            runner.call(["docs", "+fetch"])
        run.return_value = subprocess.CompletedProcess([], 10, '', '{"error":{"subtype":"confirmation_required"}}')
        with self.assertRaisesRegex(SyncError, "confirmation_required_no_bypass"):
            runner.call(["docs", "+update"])
        self.assertEqual(run.call_count, 2)


if __name__ == "__main__":
    unittest.main()
