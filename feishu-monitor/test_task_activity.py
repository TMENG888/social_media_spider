import unittest
from task_activity import leased_activity, annotate_video_activity, activity_text


class TaskActivityTests(unittest.TestCase):
    def test_attempt_is_inclusive_of_current_claim(self):
        self.assertEqual(leased_activity('1')[0], 'new')
        for value in ('2', '10', 3):self.assertEqual(leased_activity(value)[0], 'retry')
        for value in (None, '', '0', '-1', 'bad', '1.0', True):
            self.assertEqual(leased_activity(value)[0], 'unknown')

    def test_recollection_is_retry_even_when_attempt_was_reset_to_one(self):
        self.assertEqual(leased_activity('1', {'policy':'reset-once-20261016-v1', 'state':'running'})[0], 'retry')
        self.assertEqual(leased_activity('1', {'policy':'reset-once-20261016-v1', 'state':'completed'})[0], 'new')

    def test_primary_stream_does_not_prove_first_attempt(self):
        worker={'taskId':'a','taskKind':'primary','observation':'executing','consumer':'pc-worker'}
        annotate_video_activity([worker], {'a':{'status':'running','worker':'pc-worker','policy':'reset-once-20261016-v1'}})
        self.assertEqual(worker['taskActivity'], 'retry')
        annotate_video_activity([worker], {'a':{'status':'running','worker':'pc-worker'}})
        self.assertEqual(worker['taskActivity'], 'unknown')

    def test_video_retry_and_explicit_preclaim_state(self):
        worker={'taskId':'a','taskKind':'video_retry','observation':'executing','consumer':'pc-worker'}
        self.assertEqual(annotate_video_activity([worker], {})[0]['taskActivity'],'retry')
        worker['taskKind']='primary'
        for before,kind in (('pending','new'),('queued','new'),('retry_pending','retry'),('recollect_pending','retry')):
            self.assertEqual(annotate_video_activity([worker],{'a':{'status':'running','previousStatus':before}})[0]['taskActivity'],kind)

    def test_another_process_or_stopped_heartbeat_never_looks_active(self):
        worker={'taskId':'a','taskKind':'primary','observation':'executing','consumer':'pc-worker'}
        record={'status':'running','worker':'different-worker','policy':'reset-once-20261016-v1'}
        self.assertEqual(annotate_video_activity([worker],{'a':record})[0]['taskActivity'],'unknown')
        worker.update(observation='stopped',taskKind='video_retry')
        self.assertEqual(annotate_video_activity([worker],{})[0]['taskActivity'],'unknown')

    def test_display_does_not_hide_unclassified_work(self):
        self.assertEqual(activity_text({'new':1,'retry':2,'unknown':1}), '新任务 1 · 重试 2 · 类型未确认 1')


if __name__ == '__main__':unittest.main()
