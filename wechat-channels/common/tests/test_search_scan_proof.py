import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / 'src'))
from search_scan_proof import POLICY, SearchEndTracker, assess_search_end, validate_scan_envelope

KEYWORD = '原关键词'


def snapshot(index, **changes):
    value = {'keyword': KEYWORD, 'pageTitle': KEYWORD + ' - 视频 - 搜一搜', 'contextValid': True,
             'loading': False, 'loadFailed': False, 'cardCount': 8, 'cardDigest': 'a' * 64,
             'scannedCount': 8, 'scrollPercent': 100., 'verticallyScrollable': True,
             'surfaceGeneration': index, 'capturedAt': f'2026-10-15T20:00:0{index}+08:00'}
    return {**value, **changes}


def proof():
    tracker = SearchEndTracker(KEYWORD, snapshot(0, scrollPercent=0), True)
    for index in range(1, 4):
        tracker.observe(snapshot(index))
    return tracker.proof


class SearchScanProofTests(unittest.TestCase):
    def test_rebuilds_require_real_bottom_and_exact_context_not_only_no_growth(self):
        self.assertTrue(assess_search_end(proof(), KEYWORD)['ok'])
        changes = [{'scrollPercent': None}, {'scrollPercent': 70}, {'verticallyScrollable': False},
                   {'loading': True}, {'loadFailed': True}, {'contextValid': False},
                   {'pageTitle': '其他词 - 视频 - 搜一搜'}, {'keyword': '其他词'},
                   {'scannedCount': 7}, {'cardCount': 9}, {'cardDigest': 'b' * 64},
                   {'surfaceGeneration': 1}, {'capturedAt': 'yesterday'}]
        for change in changes:
            with self.subTest(change=change):
                changed = proof(); changed['observations'][-1].update(change)
                self.assertFalse(assess_search_end(changed, KEYWORD)['ok'])

    def test_legacy_completion_flag_and_old_date_window_are_never_proof(self):
        for old in [None, {'ok': True}, {'status': 'complete_exhausted'},
                    {'scanCompleted': True}, {'reason': 'year_window', 'old_streak': 100}]:
            self.assertFalse(assess_search_end(old, KEYWORD)['ok'])
        for change in [{'scanStartedAtTop': False}, {'origin': snapshot(0, scrollPercent=55)}]:
            changed = proof(); changed.update(change)
            self.assertFalse(assess_search_end(changed, KEYWORD)['ok'])

    def test_marker_cannot_be_from_card_or_sidebar_or_offscreen(self):
        changed = proof()
        for entry in changed['observations']:
            entry.update(scrollPercent=None, terminalText='没有更多了', terminalOutsideCards=True,
                         terminalBelowCards=True, lastCardInViewport=True)
        self.assertTrue(assess_search_end(changed, KEYWORD)['ok'])
        for field in ['terminalOutsideCards', 'terminalBelowCards', 'lastCardInViewport']:
            bad = copy.deepcopy(changed); bad['observations'][-1][field] = False
            self.assertFalse(assess_search_end(bad, KEYWORD)['ok'])

    def test_three_distinct_rebuild_observations_and_valid_origin_required(self):
        tracker = SearchEndTracker(KEYWORD, snapshot(0, scrollPercent=0), True)
        self.assertFalse(tracker.observe(snapshot(1))['ok'])
        self.assertFalse(tracker.observe(snapshot(2))['ok'])
        self.assertTrue(tracker.observe(snapshot(3))['ok'])
        self.assertFalse(tracker.observe(snapshot(4, scrollPercent=None))['ok'])

    def test_envelope_binds_original_task_generation_and_fresh_process_not_old_report(self):
        expected = {'taskId': 'original-task', 'topic': 'topic1', 'keyword': KEYWORD,
                    'runId': 'campaign', 'generation': 'original-generation', 'runToken': 'a' * 32}
        envelope = {**expected, 'policy': POLICY, 'startedAt': '2026-10-15T20:00:00+08:00',
                    'finishedAt': '2026-10-15T20:00:04+08:00',
                    'summaries': [{'keyword': KEYWORD, 'complete': True, 'searchEndProof': proof()}]}
        self.assertTrue(validate_scan_envelope(envelope, expected)['ok'])
        for field in expected:
            bad = copy.deepcopy(envelope); bad[field] = 'stale-or-other'
            self.assertFalse(validate_scan_envelope(bad, expected)['ok'])
        for change in [{'summaries': []}, {'finishedAt': '2026-10-14T20:00:04+08:00'},
                       {'summaries': [{'keyword': KEYWORD, 'complete': True}]}]:
            bad = copy.deepcopy(envelope); bad.update(change)
            self.assertFalse(validate_scan_envelope(bad, expected)['ok'])
