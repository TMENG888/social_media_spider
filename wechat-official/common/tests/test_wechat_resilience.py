import importlib.util
import os
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch


SOURCE = Path(__file__).parents[1] / "src" / "wechat_pc_collector.py"
SPEC = importlib.util.spec_from_file_location("wechat_pc_collector_resilience", SOURCE)
collector = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = collector
SPEC.loader.exec_module(collector)


class FakeDocument:
    def __init__(self, name):
        self.name = name

    def window_text(self):
        return self.name


class FakeWebSurface:
    def __init__(self, document_name):
        self.document_name = document_name
        self.focused = False

    def descendants(self, control_type=None):
        return [FakeDocument(self.document_name)] if control_type == "Document" else []

    def set_focus(self):
        self.focused = True


class WechatResilienceTests(unittest.TestCase):
    def test_corrupt_sqlite_is_archived_and_recreated(self):
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "topic1.sqlite"
            db_path.write_bytes(b"this is not sqlite")
            connection = collector.init_state(db_path)
            try:
                self.assertEqual(
                    connection.execute("PRAGMA quick_check").fetchone()[0], "ok"
                )
                self.assertIsNotNone(connection.execute(
                    "SELECT name FROM sqlite_master WHERE name='captured_article'"
                ).fetchone())
            finally:
                connection.close()
            archived = list((db_path.parent / "corrupt-state").rglob("topic1.sqlite"))
            self.assertEqual(len(archived), 1)
            self.assertEqual(archived[0].read_bytes(), b"this is not sqlite")

    def test_lastgood_backup_restores_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "topic2.sqlite"
            connection = collector.init_state(db_path)
            collector.update_task_state(
                connection, "北京臻澐", "专题二", 17, 0, "running"
            )
            collector.checkpoint_state_backup(connection, force=True)
            connection.close()
            db_path.write_bytes(b"broken after checkpoint")
            recovered = collector.init_state(db_path)
            try:
                row = recovered.execute(
                    "SELECT next_result_index FROM crawl_task WHERE keyword=?",
                    ("北京臻澐",),
                ).fetchone()
                self.assertEqual(row[0], 17)
            finally:
                recovered.close()

    def test_publish_time_accepts_detail_and_card_formats(self):
        self.assertEqual(
            collector.parse_publish_time([("2026年9月17日 08:30", "Text", "")]),
            datetime(2026, 9, 17, 8, 30),
        )
        self.assertEqual(
            collector.parse_publish_time([("2026-09-18 12:05", "Text", "")]),
            datetime(2026, 9, 18, 12, 5),
        )

    def test_same_title_different_author_has_different_identity(self):
        first = collector.article_identity_key(
            "同一篇住宅文章", "公众号甲", "2026-09-18 08:00:00"
        )
        second = collector.article_identity_key(
            "同一篇住宅文章", "公众号乙", "2026-09-18 08:00:00"
        )
        self.assertNotEqual(first, second)

    def test_card_author_requires_semantic_node(self):
        records = [
            ("同一篇住宅文章", "Text", "article-title"),
            ("这是一段摘要", "Text", "article-summary"),
            ("公众号甲", "Hyperlink", "account-nickname wx_tap_link"),
            ("2026年9月18日", "Text", "publish-time"),
        ]
        self.assertEqual(
            collector.parse_search_card_author(records, "同一篇住宅文章"),
            "公众号甲",
        )
        self.assertIsNone(collector.parse_search_card_author(
            [("可能是摘要", "Text", "plain-text")], "同一篇住宅文章"
        ))

    def test_duplicate_identity_is_not_safe_for_no_open_skip(self):
        key = collector.article_identity_key(
            "同一篇住宅文章", "公众号甲", "2026-09-18 08:00:00"
        )
        counts = {key: 2}
        self.assertNotEqual(counts.get(key), 1)

    def test_position_fingerprint_distinguishes_card_excerpt(self):
        first = [
            ("同一标题", "Text", "article-title"),
            ("公众号甲", "Hyperlink", "account-nickname"),
            ("2026年9月18日", "Text", "publish-time"),
            ("摘要甲", "Text", "article-summary"),
        ]
        second = [
            ("同一标题", "Text", "article-title"),
            ("公众号甲", "Hyperlink", "account-nickname"),
            ("2026年9月18日", "Text", "publish-time"),
            ("摘要乙", "Text", "article-summary"),
        ]
        self.assertNotEqual(
            collector.search_card_fingerprint("同一标题", first),
            collector.search_card_fingerprint("同一标题", second),
        )

    def test_position_fingerprint_requires_author_and_date(self):
        self.assertIsNone(collector.search_card_fingerprint(
            "标题", [("只有摘要", "Text", "article-summary")]
        ))

    def test_150_percent_fallback_coordinate_scaling(self):
        with patch.dict(os.environ, {"WECHAT_DISPLAY_SCALE": "150"}):
            self.assertEqual(collector.scale_pixels(28), 42)
            self.assertEqual(collector.scale_pixels(75), 112)
        with patch.dict(os.environ, {"WECHAT_DISPLAY_SCALE": "100"}):
            self.assertEqual(collector.scale_pixels(28), 28)
        source = SOURCE.read_text(encoding="utf-8")
        self.assertIn("rect.left + scale_pixels(search_box[0])", source)
        self.assertIn("rect.top + scale_pixels(search_box[1])", source)

    def test_completed_scan_is_not_downgraded_by_one_bad_article(self):
        source = SOURCE.read_text(encoding="utf-8")
        self.assertIn('and not status.startswith("complete_")', source)
        self.assertIn('"article_skipped_missing_publish_time"', source)

    def test_worker_never_advances_after_unfinished_keyword(self):
        worker = (SOURCE.parents[1] / "run-worker.ps1").read_text(encoding="utf-8-sig")
        self.assertIn("stopping before the next keyword so no task is skipped", worker)
        self.assertIn("$stopTaskForUnfinishedKeyword = $true", worker)
        self.assertNotIn("not retrying in place. Continuing to the next keyword", worker)

    def test_stacked_detail_tabs_close_until_search_results(self):
        surface = FakeWebSurface("公众号文章")
        close_count = 0

        def close_active_tab(_keys, **_kwargs):
            nonlocal close_count
            close_count += 1
            surface.document_name = "搜一搜" if close_count >= 3 else "公众号文章"

        with patch.object(
            collector, "web_windows", return_value=[surface]
        ), patch.object(
            collector.keyboard, "send_keys", side_effect=close_active_tab
        ), patch.object(collector.time, "sleep", return_value=None):
            closed = collector.close_stacked_detail_tabs_until_search_results(surface)
        self.assertEqual(closed, 3)
        self.assertEqual(close_count, 3)
        self.assertTrue(collector.is_search_results_page(surface))

    def test_stacked_detail_tab_cleanup_is_bounded(self):
        surface = FakeWebSurface("公众号文章")
        with patch.object(
            collector, "web_windows", return_value=[surface]
        ), patch.object(
            collector.keyboard, "send_keys", return_value=None
        ), patch.object(collector.time, "sleep", return_value=None):
            with self.assertRaises(collector.SearchWindowUnavailableError):
                collector.close_stacked_detail_tabs_until_search_results(
                    surface, max_tabs=2,
                )


if __name__ == "__main__":
    unittest.main()
