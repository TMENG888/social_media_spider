import ast
import inspect
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / 'src'))
import channels_pc_collector as collector


class AnnualDateBoundaryTests(unittest.TestCase):
    def test_old_date_threshold_is_diagnostic_even_with_one_or_many_old_results(self):
        for threshold in (1, 8):
            for streak in (0, 1, 8, 100):
                self.assertEqual(collector.observe_old_date_window(
                    {'cutoff_old_streak': threshold}, streak), streak >= threshold)
        source = inspect.getsource(collector.collect_live_keyword)
        tree = ast.parse(source)
        # Both the cached-video branch and freshly collected-video branch
        # must retain their next iteration instead of manufacturing completion.
        self.assertEqual(source.count('if observe_old_date_window(config, old_streak):'), 2)
        for node in ast.walk(tree):
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                value = node.value
                self.assertFalse(isinstance(value, ast.Constant) and value.value == 'complete_cutoff')
            if isinstance(node, ast.If) and isinstance(node.test, ast.Call):
                if isinstance(node.test.func, ast.Name) and node.test.func.id == 'observe_old_date_window':
                    self.assertFalse(any(isinstance(child, (ast.Break, ast.Return)) for child in ast.walk(node)))

    def test_exact_claimed_legacy_scan_restarts_from_top_without_reopening_item_history(self):
        for status in ('complete_cutoff', 'complete_cutoff_with_deferred_retry',
                       'complete_cutoff_with_dead_letters', 'complete_explicit_empty',
                       'complete_exhausted', 'complete_exhausted_with_deferred_retry'):
            self.assertTrue(collector.legacy_annual_rescan_required(status))
            self.assertFalse(collector.legacy_annual_rescan_required(status, asr_backfill=True))
        self.assertTrue(collector.legacy_annual_rescan_required('complete_cutoff', recheck_exhausted=False))
        self.assertFalse(collector.legacy_annual_rescan_required('complete_exhausted', recheck_exhausted=False))
        for status in ('running', 'partial_stopped', ''):
            self.assertFalse(collector.legacy_annual_rescan_required(status))
        source = inspect.getsource(collector.collect_live_keyword)
        replay = source.split('if recheck_annual:', 1)[1].split('if previous_status.startswith', 1)[0]
        self.assertIn('result_index = 0', replay)
        self.assertIn('old_streak = 0', replay)
        self.assertNotIn('connection.execute', replay)
        self.assertNotIn('remote_store.', replay)


if __name__ == '__main__':
    unittest.main()
