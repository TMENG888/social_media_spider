import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).parents[1]/'src'))
import redis_task_queue as q
import video_retry_budget as budget


class RetryAckFenceTests(unittest.TestCase):
    def setUp(self):
        self.args=SimpleNamespace(prefix='isolated-fixture',redis_url='not-used',redis_password=None,consumer='worker')
        self.item={'task_id':'original','fingerprint':'fp'}

    def test_ack_passes_the_exact_validated_bytes_not_just_terminal_status(self):
        encoded=json.dumps({'status':'completed','retry_count':2})
        with patch.object(q,'redis_command',side_effect=[encoded,1]) as redis:
            self.assertEqual(budget.acknowledge_terminal(q,self.args,'stream','group','1-0',self.item),1)
        self.assertEqual(redis.call_args.args[-1],encoded)
        self.assertIn("raw~=ARGV[5]",budget.ACK_TERMINAL)
        self.assertIn('RETRY_CHECKPOINT_CHANGED',budget.ACK_TERMINAL)

    def test_bad_completed_checkpoint_cannot_ack_even_if_caller_guard_is_stale(self):
        cp={'status':'completed','row':{'video_content':'中文字幕志愿者刘娅中文字幕组'}}
        with patch.object(q,'redis_command',return_value=json.dumps(cp)) as redis:
            with self.assertRaisesRegex(q.RedisError,'REQUIRES_REPAIR'):
                budget.acknowledge_terminal(q,self.args,'stream','group','1-0',self.item)
        self.assertEqual(redis.call_count,1)

    def test_invalid_nonterminal_and_dead_letter_never_ack(self):
        for encoded in ('null','[]','bad',json.dumps({'status':'retry_pending'}),json.dumps({'status':'dead_letter'})):
            with self.subTest(encoded=encoded),patch.object(q,'redis_command',return_value=encoded) as redis:
                with self.assertRaises(q.RedisError):
                    budget.acknowledge_terminal(q,self.args,'stream','group','1-0',self.item)
                self.assertEqual(redis.call_count,1)

    def test_explicit_unresolved_skip_remains_terminal_not_success(self):
        encoded=json.dumps({'status':'skipped_unresolved','row':{'video_content':'中文字幕组'}})
        with patch.object(q,'redis_command',side_effect=[encoded,1]):
            self.assertEqual(budget.acknowledge_terminal(q,self.args,'stream','group','1-0',self.item),1)


if __name__=='__main__':
    unittest.main()
