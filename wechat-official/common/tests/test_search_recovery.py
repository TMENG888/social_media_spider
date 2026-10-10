import importlib.util
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


SOURCE = Path(__file__).parents[1] / "src" / "wechat_pc_collector.py"
SPEC = importlib.util.spec_from_file_location("wechat_pc_collector", SOURCE)
collector = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = collector
SPEC.loader.exec_module(collector)


class SearchRecoveryTests(unittest.TestCase):
    def setUp(self):
        collector.STOP_REQUESTED = False

    def test_first_missing_surface_is_recovered_without_changing_keyword(self):
        config = {
            "search_window_recovery_attempts": 3,
            "search_window_recovery_wait_seconds": 0,
        }
        with patch.object(
            collector,
            "_search_in_web_once",
            side_effect=[collector.SearchWindowUnavailableError("transient"), None],
        ) as open_search, patch.object(
            collector, "get_search_window", return_value=object()
        ), patch.object(
            collector, "is_article_results_page", return_value=True
        ):
            collector.search_in_web("中海 玖序", config)
        self.assertEqual(open_search.call_count, 2)
        self.assertEqual(open_search.call_args.args[0], "中海 玖序")

    def test_recovery_is_bounded(self):
        config = {
            "search_window_recovery_attempts": 3,
            "search_window_recovery_wait_seconds": 0,
        }
        with patch.object(
            collector,
            "_search_in_web_once",
            side_effect=RuntimeError("still missing"),
        ) as open_search:
            with self.assertRaises(collector.SearchWindowUnavailableError):
                collector.search_in_web("中海 玖序", config)
        self.assertEqual(open_search.call_count, 3)

    def test_worker_retries_same_keyword_but_honours_safe_stop(self):
        worker = (Path(__file__).parents[1] / "run-worker.ps1").read_text(encoding="utf-8-sig")
        self.assertIn("$collectorAttempt -ge $keywordRetryAttempts", worker)
        self.assertIn("if (Test-Path $stopFile)", worker)
        self.assertIn("staying on the same keyword", worker)

    def test_recovery_settings_are_finite(self):
        config = json.loads((Path(__file__).parents[1] / "collector_config.json").read_text(encoding="utf-8"))
        self.assertEqual(config["search_window_recovery_attempts"], 3)
        self.assertEqual(config["keyword_retry_attempts"], 5)
        self.assertGreater(config["keyword_retry_backoff_seconds"], 0)

    def test_deep_result_uses_scrollitem_then_refreshes_uia_object(self):
        class Rect:
            def __init__(self, left, top, right, bottom):
                self.left, self.top, self.right, self.bottom = left, top, right, bottom

            def width(self):
                return self.right - self.left

            def height(self):
                return self.bottom - self.top

        class Document:
            def rectangle(self):
                return Rect(0, 0, 1200, 900)

            def is_visible(self):
                return True

        class Surface:
            def descendants(self, control_type=None):
                return [Document()] if control_type == "Document" else []

            def set_focus(self):
                pass

        position = {"top": 8000, "scroll_calls": 0}

        class Result:
            def rectangle(self):
                return Rect(100, position["top"], 1000, position["top"] + 120)

            def scroll_into_view(self):
                position["scroll_calls"] += 1
                position["top"] = 400

        results = [Result() for _ in range(77)]
        with patch.object(collector, "get_search_window", return_value=Surface()), patch.object(
            collector, "search_result_buttons", return_value=results
        ), patch.object(collector.time, "sleep", return_value=None):
            found = collector.bring_search_result_into_view(76, {"result_scroll_rounds": 120})

        self.assertIsNotNone(found)
        self.assertEqual(position["scroll_calls"], 1)

    def test_position_failure_is_audited_and_advances_checkpoint(self):
        source = SOURCE.read_text(encoding="utf-8")
        self.assertIn('status = "partial_position_error"', source)
        self.assertIn('"checkpoint_advanced": True', source)
        self.assertIn('"position_unreachable_skipped"', source)
        self.assertIn('"search_result_position_circuit_breaker"', source)
        self.assertIn("search_in_web(keyword, config)", source)


if __name__ == "__main__":
    unittest.main()
