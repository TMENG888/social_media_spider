import sys
import unittest
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch, MagicMock
sys.path.insert(0, str(Path(__file__).parents[1] / 'src'))
import redis_task_queue as q
import retry_priority as priority


class PriorityTests(unittest.TestCase):
    def setUp(self):
        self.args = SimpleNamespace(redis_url='redis://test', redis_password=None,
            retry_stream='retry', retry_group='retry-group', consumer='worker', reclaim_idle_seconds=300)
        self.adapter = SimpleNamespace(read_new=Mock(return_value=None), auto_claim=Mock(return_value=None),
            pending_count=Mock(return_value=0), group_lag=Mock(return_value=0))

    def test_retry_claimed_before_any_keyword_admission(self):
        self.adapter.read_new.return_value = ('1-0', {'fingerprint': 'a'})
        message, hold, _ = priority.claim_retry_first(self.adapter, self.args)
        self.assertEqual(message[0], '1-0'); self.assertTrue(hold)
        self.adapter.auto_claim.assert_not_called()

    def test_expired_other_worker_retry_reclaimed(self):
        self.adapter.auto_claim.return_value = ('2-0', {'fingerprint': 'b'})
        self.assertEqual(priority.claim_retry_first(self.adapter, self.args)[0][0], '2-0')

    def test_inflight_retry_on_other_worker_blocks_new_keywords(self):
        self.adapter.pending_count.return_value = 1
        with patch.object(priority, 'unresolved_checkpoints') as audit:
            message, hold, detail = priority.claim_retry_first(self.adapter, self.args)
        self.assertIsNone(message); self.assertTrue(hold); audit.assert_not_called()
        self.assertEqual(detail['reason'], 'retry_messages_outstanding')

    def test_unread_retries_block_new_keywords(self):
        self.adapter.group_lag.return_value = 3
        self.assertTrue(priority.claim_retry_first(self.adapter, self.args)[1])

    def test_checkpoint_backlog_blocks_even_when_queue_empty(self):
        with patch.object(priority, 'unresolved_checkpoints', return_value={'dead_letter': 1}) as audit:
            first = priority.claim_retry_first(self.adapter, self.args)
            second = priority.claim_retry_first(self.adapter, self.args)
        self.assertTrue(first[1]); self.assertTrue(second[1]); self.assertEqual(audit.call_count, 1)

    def test_clean_queue_and_checkpoints_admit_next_keyword(self):
        with patch.object(priority, 'unresolved_checkpoints', return_value={}):
            self.assertFalse(priority.claim_retry_first(self.adapter, self.args)[1])

    def test_network_failure_does_not_admit_primary(self):
        self.adapter.read_new.side_effect = TimeoutError()
        with self.assertRaises(TimeoutError):priority.claim_retry_first(self.adapter, self.args)

    def test_completed_with_pollution_or_review_still_blocks(self):
        self.assertEqual(priority.checkpoint_blocker({'status':'completed','row':{'video_content':'全国地产设计产品力监测'}}),'polluted_subtitle')
        self.assertEqual(priority.checkpoint_blocker({'status':'completed','subtitle_review_required':True}),'subtitle_review')
        self.assertIsNone(priority.checkpoint_blocker({'status':'completed','row':{'video_content':'正常口播有错别字也不因此重采'}}))

    def test_dead_letter_is_not_successfully_complete(self):
        self.assertEqual(priority.checkpoint_blocker({'status':'dead_letter'}),'dead_letter')

    def test_unknown_lag_uses_actual_unread_entries(self):
        groups=[['name','g','lag',None,'last-delivered-id','1-0']]
        with patch.object(q,'redis_command',side_effect=[groups,[]]) as command:
            self.assertEqual(q.group_lag('url',None,'s','g'),0)
        self.assertEqual(command.call_args.args[2:],('XRANGE','s','(1-0','+','COUNT',1))
        with patch.object(q,'redis_command',side_effect=[groups,[['2-0',[]]]]):
            self.assertEqual(q.group_lag('url',None,'s','g'),1)

    def test_cli_default_strict_mixed(self):
        args=q.build_parser().parse_args(['run','--queue','q','--common','c','--worker-root','w'])
        self.assertEqual(args.task_priority,'retry_first')

    def loop_args(self, root):
        return SimpleNamespace(prefix='wechat:channels:test-priority-loop',redis_url='redis://test',redis_password=None,
            retry_stream='retry',retry_group='retry-group',stream='primary',group='primary-group',
            consumer='test-worker',worker_root=Path(root),block_seconds=1,reclaim_idle_seconds=300,
            task_priority='retry_first',once=True)

    def test_production_loop_launches_retry_not_keyword(self):
        with tempfile.TemporaryDirectory() as root:
            args=self.loop_args(root);stop=MagicMock();stop.is_set.return_value=False
            control=MagicMock();control.poll.return_value=False;asr=MagicMock()
            item={'task_id':'topic1:test','topic':'topic1','keyword':'test','fingerprint':'fp'}
            guards=[{'ok':False,'status':'retry_pending'},{'ok':False,'status':'retry_pending'},{'ok':True,'status':'completed'}]
            budget_start=patch('video_retry_budget.begin',return_value={'allowed':True,'attempts':1,'token':'test'})
            budget_finish=patch('video_retry_budget.finish',return_value={'state':'accepted'})
            budget_start.start();budget_finish.start()
            self.addCleanup(budget_start.stop);self.addCleanup(budget_finish.stop)
            with patch('retry_round.claim_round',return_value=(False,None,None,None)), patch.object(priority,'claim_retry_first',return_value=(('1-0',item),True,{})), patch.object(q,'claim_primary_message') as primary, patch.object(q,'run_task',return_value=0) as child, patch.object(q,'video_retry_completion_guard',side_effect=guards), patch.object(q,'refresh_parent_keyword_status',return_value={}), patch.object(q,'publish_remote_log'), patch.object(q,'redis_command'):
                result=q._worker_loop(args,stop,control,Path(root)/'stop',Path(root)/'status.json',asr,'mixed',1,1)
            self.assertEqual(result,0);primary.assert_not_called()
            self.assertEqual(child.call_args.kwargs['task_kind'],'video_retry')

    def test_production_loop_waits_when_other_worker_owns_retry(self):
        with tempfile.TemporaryDirectory() as root:
            args=self.loop_args(root);stop=MagicMock();stop.is_set.side_effect=[False,True]
            control=MagicMock();control.poll.return_value=False
            with patch('retry_round.claim_round',return_value=(False,None,None,None)), patch.object(priority,'claim_retry_first',return_value=(None,True,{'reason':'retry_messages_outstanding','pending':1})), patch.object(q,'claim_primary_message') as primary, patch.object(q,'run_task') as child, patch.object(q,'publish_remote_log'):
                q._worker_loop(args,stop,control,Path(root)/'stop',Path(root)/'status.json',MagicMock(),'mixed',1,1)
            primary.assert_not_called();child.assert_not_called();stop.wait.assert_called_once()

    def test_production_loop_enters_next_keyword_only_after_gate_clear(self):
        with tempfile.TemporaryDirectory() as root:
            args=self.loop_args(root);stop=MagicMock();stop.is_set.return_value=False
            control=MagicMock();control.poll.return_value=False
            item={'task_id':'topic1:new','topic':'topic1','keyword':'new keyword'}
            with patch('retry_round.claim_round',return_value=(False,None,None,None)), patch.object(priority,'claim_retry_first',return_value=(None,False,{})), patch.object(q,'claim_primary_message',return_value=(('2-0',item),False)) as primary, patch.object(q,'run_task',return_value=0) as child, patch.object(q,'checkpoint_completion_guard',return_value={'ok':True,'deferredCount':0}), patch.object(q,'update_remote_status'), patch.object(q,'publish_remote_log'), patch.object(q,'redis_command'):
                result=q._worker_loop(args,stop,control,Path(root)/'stop',Path(root)/'status.json',MagicMock(),'mixed',1,1)
            self.assertEqual(result,0);primary.assert_called_once()
            self.assertEqual(child.call_args.kwargs['task_kind'],'primary')


if __name__ == '__main__': unittest.main()
