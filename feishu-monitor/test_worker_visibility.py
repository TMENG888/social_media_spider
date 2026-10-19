import copy
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from worker_visibility import current_worker_rows
from notification import brief_notification, SECTION_TITLES
from publish import alert_signature, summary


class CurrentWorkerVisibilityTests(unittest.TestCase):
    def row(self, computer, state, worker='worker-02', **extra):
        return dict(computer=computer, worker=worker, observation=state, **extra)

    def test_all_live_machines_preserved_old_same_slot_hidden(self):
        rows = [self.row('pc-a', 'executing', taskActivity='retry'),
                self.row('pc-b', 'executing', taskActivity='new'),
                self.row('old-pc', 'heartbeat_stale'),
                self.row('old-pc2', 'registration_unobserved'),
                self.row('old-pc3', 'stopped')]
        original = copy.deepcopy(rows)
        self.assertEqual(current_worker_rows(rows), rows[:2])
        self.assertEqual(rows, original)
        snapshot = {'workers': rows}
        text, _ = brief_notification(snapshot, {})
        self.assertIn('当前在线 2台 · 执行 2节点（新任务 1 · 重试 1）', text)
        self.assertNotIn('old-pc', text)
        self.assertEqual(alert_signature(snapshot, {}), alert_signature({'workers': rows[:2]}, {}))
        self.assertIn('old-pc', summary(snapshot, {}))

    def test_unreplaced_failure_and_fresh_abnormal_states_retained(self):
        for state in ('heartbeat_stale', 'registration_unobserved', 'stopped',
                      'clock_skew', 'exit_unconfirmed', 'draining'):
            with self.subTest(state=state):
                row = self.row('pc-a', state)
                self.assertEqual(current_worker_rows([row]), [row])
        rows = [self.row('pc-a', 'executing'), self.row('pc-b', 'clock_skew'),
                self.row('pc-c', 'exit_unconfirmed'), self.row('pc-d', 'draining'),
                self.row('pc-e', 'heartbeat_stale', worker='worker-01')]
        self.assertEqual(current_worker_rows(rows), rows)

    def test_unknown_machine_cannot_suppress_offline_evidence(self):
        for computer in (None, '', 'unknown'):
            rows = [self.row(computer, 'executing'), self.row('old-pc', 'heartbeat_stale')]
            self.assertEqual(current_worker_rows(rows), rows)

    def test_waiting_resting_and_cooldown_are_live_replacements(self):
        for state in ('online_waiting', 'resting', 'cooldown'):
            rows = [self.row('pc-a', state), self.row('old-pc', 'heartbeat_stale')]
            self.assertEqual(current_worker_rows(rows), rows[:1])

    def test_same_computer_multiple_workers_is_one_machine_multiple_nodes(self):
        rows = [self.row('pc-a', 'executing'),
                self.row('pc-a', 'executing', worker='worker-03'),
                self.row('old-pc', 'heartbeat_stale')]
        text, _ = brief_notification({'workers': rows}, {})
        self.assertIn('当前在线 1台 · 执行 2节点', text)
        self.assertNotIn('old-pc', text)

    def test_platform_scope_and_telemetry_denominator(self):
        def platform(name, rows):
            return {'platform': name, 'source': 'ok', 'counts': {'total': 1, 'validLeases': 0},
                    'telemetry': {'machines': rows}}
        snapshot = {'workers': [self.row('video-pc', 'executing')], 'platformTasks': [
            platform('小红书', [self.row('xhs-old', 'heartbeat_stale')]),
            platform('抖音', [self.row('dy-a', 'executing'), self.row('dy-b', 'cooldown'),
                             self.row('dy-old', 'heartbeat_stale')])]}
        original = json.dumps(snapshot, sort_keys=True)
        text, _ = brief_notification(snapshot, {}, include_diagnostics=True)
        machine_block = text.split(SECTION_TITLES[1])[1].split(SECTION_TITLES[2])[0]
        self.assertIn('小红书：0/1 在线', machine_block)
        self.assertIn('抖音：2/2 在线（已上报） · 休眠/冷却 1', machine_block)
        self.assertIn('小红书心跳异常1台', text)
        self.assertNotIn('抖音心跳异常', text)
        self.assertEqual(json.dumps(snapshot, sort_keys=True), original)


if __name__ == '__main__':
    unittest.main()
