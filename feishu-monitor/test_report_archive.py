import json
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from report_archive import archive_confirmed, render_recent_day


class ArchiveTests(unittest.TestCase):
    def test_public_archive_does_not_claim_an_enabled_schedule_or_private_wiki(self):
        with tempfile.TemporaryDirectory() as out:
            render_recent_day(out, 1791855752)
            text = (Path(out) / 'recent-day-reports.md').read_text(encoding='utf-8')
            self.assertNotIn('09:00', text)
            self.assertNotIn('feishu.cn/wiki/', text)

    def add(self, out, when, text="four blocks"):
        return archive_confirmed(out, {"generatedAt": "sample", "sources": {"redis": "ok"}},
                                 {"source": "ok"}, {"card": text}, text, when)

    def test_exact_text_and_ack_are_preserved(self):
        with tempfile.TemporaryDirectory() as out:
            path = self.add(out, 1791855752)
            entry = json.loads(path.read_text(encoding="utf-8"))
            self.assertTrue(entry["deliveryConfirmed"])
            self.assertEqual(entry["text"], "four blocks")
            self.assertEqual(path.parent.name, "2026-10-13")

    def test_idempotent_same_ack(self):
        with tempfile.TemporaryDirectory() as out:
            self.add(out, 1791855752)
            self.add(out, 1791855752)
            self.assertEqual(len(list(Path(out).glob("report-history/*/*.json"))), 1)

    def test_same_payload_at_different_times_is_not_lost(self):
        with tempfile.TemporaryDirectory() as out:
            self.add(out, 1791855752)
            self.add(out, 1791855753)
            self.assertEqual(len(render_recent_day(out, 1791855753)), 2)

    def test_rolling_window_excludes_old_and_future_but_keeps_history(self):
        with tempfile.TemporaryDirectory() as out:
            self.add(out, 1791855752 - 86401, "old")
            self.add(out, 1791855752, "current")
            self.add(out, 1791855753, "future")
            entries = render_recent_day(out, 1791855752)
            self.assertEqual([e["text"] for e in entries], ["current"])
            self.assertEqual(len(list(Path(out).glob("report-history/*/*.json"))), 3)

    def test_no_history_is_unknown_not_zero_delivery(self):
        with tempfile.TemporaryDirectory() as out:
            self.assertEqual(render_recent_day(out, 1791855752), [])
            text = (Path(out) / "recent-day-reports.md").read_text(encoding="utf-8")
            self.assertIn("不等于群内没有历史消息", text)
            self.assertIn("云端更新须单独回读确认", text)
            self.assertEqual((Path(out) / "cloud-log-body.txt").read_text(encoding="utf-8"),
                             text.split("\n", 2)[2])


if __name__ == "__main__":
    unittest.main()
