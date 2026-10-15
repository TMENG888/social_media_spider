import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parents[1] / 'src'))
import redis_worker_control as control
import redis_task_queue as scheduler


class MemoryRedis:
    def __init__(self):
        self.hashes = {}
        self.calls = []
        self.failed = False

    def __call__(self, url, password, op, *args, **kwargs):
        if self.failed:
            raise TimeoutError('offline')
        self.calls.append((op, *args))
        if op == 'HGET':
            return self.hashes.get(args[0], {}).get(args[1])
        if op == 'HSET':
            self.hashes.setdefault(args[0], {})[args[1]] = args[2]
            return 1
        if op == 'EVAL':
            _, _, key, target, command_id = args
            raw = self.hashes.get(key, {}).get(target)
            if not raw:
                return 0
            if json.loads(raw)['commandId'] != command_id:
                return -1
            del self.hashes[key][target]
            return 1
        raise AssertionError(op)


def make_args(root):
    queue_file = root / 'queue.json'
    queue_file.write_text('{"tasks": []}', encoding='utf-8')
    prefix = 'wechat:channels:unit-control'
    return SimpleNamespace(worker_root=root / 'worker-03', queue=queue_file,
        prefix=prefix, redis_url='redis://test/0', redis_password=None,
        consumer='HOST-worker-03-1', stream=prefix+':tasks',
        retry_stream=prefix+':video-retry', group='workers', retry_group='workers-video-retry',
        seeded_key=prefix+':seeded', status_key=prefix+':status', common=root,
        block_seconds=1, reclaim_idle_seconds=300, heartbeat_seconds=30,
        heartbeat_failure_limit=3, once=False)


class WorkerControlTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.args = make_args(Path(self.temp.name))
        self.redis = MemoryRedis()
        self.event = threading.Event()
        self.receiver = control.WorkerControl(self.args, self.event, self.redis, computer='HOST', interval=.01)
        self.addCleanup(self.receiver.close)

    def send(self, computer='HOST', worker='worker-03'):
        return control.send_stop(self.redis, '', None, self.args.prefix, computer, worker)

    def test_target_requires_exact_identity(self):
        self.assertEqual(control.target_key(' host ', 'WORKER-03'), 'HOST|worker-03')
        for comp, worker in [('', 'worker-01'), ('*', 'worker-01'), ('HOST', '*'), ('HOST|other', 'worker-01')]:
            with self.assertRaises(ValueError):
                control.target_key(comp, worker)

    def test_registry_contains_task_and_lease_metadata(self):
        state=self.args.worker_root / '.state' / 'redis_worker_status.json'
        state.parent.mkdir(parents=True,exist_ok=True)
        state.write_text(json.dumps({'taskId':'t','keyword':'K','status':'running','messageId':'1-0','startedAt':'2026-10-12T17:00:00+08:00','taskKind':'video_retry','leaseStream':self.args.retry_stream,'leaseGroup':self.args.retry_group}),encoding='utf-8')
        self.args.run_generation='g'
        self.receiver.registry('running')
        r=json.loads(self.redis.hashes[self.args.prefix+':worker-registry'][self.args.consumer])
        self.assertEqual(r['generation'],'g');self.assertEqual(r['messageId'],'1-0')
        self.assertEqual(r['leaseReclaimSeconds'],300);self.assertEqual(r['taskKind'],'video_retry')

    def test_other_host_or_worker_unaffected(self):
        self.send('OTHER')
        self.send(worker='worker-02')
        self.receiver.poll()
        self.assertFalse(self.event.is_set())
        self.assertFalse(self.receiver.stop_file.exists())

    def test_draining_and_stopped_ack_keep_checkpoints(self):
        checkpoint = self.args.worker_root / '.state' / 'topic1.sqlite'
        checkpoint.parent.mkdir(parents=True)
        checkpoint.write_bytes(b'untouched-checkpoint')
        request = self.send()
        self.receiver.poll()
        self.assertTrue(self.event.is_set())
        self.assertTrue(self.receiver.stop_file.exists())
        ack_key = self.args.prefix+':worker-control-acks'
        self.assertEqual(json.loads(self.redis.hashes[ack_key][self.args.consumer])['status'], 'draining')
        self.receiver.close(orderly=True)
        self.assertEqual(json.loads(self.redis.hashes[ack_key][self.args.consumer])['status'], 'stopped')
        self.assertEqual(checkpoint.read_bytes(), b'untouched-checkpoint')
        self.assertEqual(json.loads(self.receiver.receipt.read_text(encoding='utf-8'))['commandId'], request['commandId'])
        self.assertFalse(any(c[0] == 'XACK' for c in self.redis.calls))

    def test_hold_survives_relaunch_until_explicit_resume(self):
        request = self.send()
        self.receiver.poll()
        event = threading.Event()
        again = control.WorkerControl(self.args, event, self.redis, computer='HOST')
        again.start()
        again.close(orderly=True)
        self.assertTrue(event.is_set())
        with self.assertRaises(ValueError):
            control.resume(self.redis, '', None, self.args.prefix, 'HOST', 'worker-03', 'stale-id')
        self.assertEqual(control.resume(self.redis, '', None, self.args.prefix, 'HOST', 'worker-03', request['commandId']), 1)
        fresh_event = threading.Event()
        fresh = control.WorkerControl(self.args, fresh_event, self.redis, computer='HOST')
        fresh.start()
        fresh.close(orderly=True)
        self.assertFalse(fresh_event.is_set())
        # Release does not cancel a draining process's event.
        self.assertTrue(self.event.is_set())

    def test_network_failure_on_startup_fails_closed(self):
        self.redis.failed = True
        with self.assertRaises(TimeoutError):
            self.receiver.start()
        self.assertIsNone(self.receiver.thread)

    def test_exception_does_not_claim_safe_stopped(self):
        self.send()
        self.receiver.poll()
        self.receiver.close(orderly=False)
        ack = json.loads(self.redis.hashes[self.args.prefix+':worker-control-acks'][self.args.consumer])
        self.assertEqual(ack['status'], 'exit_unconfirmed')

    def test_background_receiver_observes_stop(self):
        self.receiver.start()
        self.send()
        self.assertTrue(self.event.wait(1))

    def test_startup_hold_does_not_seed_or_claim(self):
        self.send()
        with patch.object(scheduler, 'redis_command', self.redis), patch.object(control.socket, 'gethostname', return_value='HOST'), patch.object(scheduler, 'seed_tasks') as seed:
            self.assertEqual(scheduler.run_worker(self.args), 130)
            seed.assert_not_called()

    def test_command_during_claim_leaves_message_pending_without_child(self):
        remote = MagicMock()
        remote.poll.side_effect = [False, True]
        message = ('1-0', {'task_id':'topic1:x', 'keyword':'test', 'topic':'topic1', 'queue':{'tasks':[]}})
        with patch.object(scheduler, 'ensure_group'), patch.object(scheduler, 'seed_tasks', return_value=0), patch.object(scheduler, 'publish_remote_log'), patch('retry_round.claim_round', return_value=(False, None, None, None)), patch.object(scheduler, 'claim_primary_message', return_value=(message, False)), patch.object(scheduler, 'run_task') as child, patch.object(scheduler, 'redis_command') as redis:
            result = scheduler._run_worker(self.args, self.event, remote)
        self.assertEqual(result, 130)
        child.assert_not_called()
        self.assertFalse(any(c.args[2:3] == ('XACK',) for c in redis.call_args_list))

    def test_active_child_saves_checkpoint_and_no_next_task(self):
        remote = MagicMock()
        remote.poll.return_value = False
        message = ('1-0', {'task_id':'topic1:x', 'keyword':'test', 'topic':'topic1', 'queue':{'tasks':[]}})
        def finish_child(*args, **kwargs):
            self.send()
            self.receiver.poll()
            (self.args.worker_root / '.state' / 'video-checkpoint.json').write_text('{"next_index": 7}')
            return 4
        guard = {'ok':False, 'deferredCount':0, 'checkpointCount':1, 'blocking':{'retry_pending':1}}
        with patch.object(scheduler, 'ensure_group'), patch.object(scheduler, 'seed_tasks', return_value=0), patch.object(scheduler, 'publish_remote_log'), patch('retry_round.claim_round', return_value=(False, None, None, None)), patch.object(scheduler, 'claim_primary_message', return_value=(message, False)) as claim, patch.object(scheduler, 'run_task', side_effect=finish_child), patch.object(scheduler, 'checkpoint_completion_guard', return_value=guard), patch.object(scheduler, 'update_remote_status'), patch.object(scheduler, 'redis_command') as redis:
            result = scheduler._run_worker(self.args, self.event, remote)
        self.assertEqual(result, 130)
        self.assertEqual(claim.call_count, 1)
        self.assertEqual(json.loads((self.args.worker_root / '.state' / 'video-checkpoint.json').read_text())['next_index'], 7)
        self.assertFalse(any(c.args[2:3] == ('XACK',) for c in redis.call_args_list))


if __name__ == '__main__':
    unittest.main()
