"""Opt-in Redis integration test. Only a unique test prefix is mutated; no RPA/MySQL."""
import json
import os
import sys
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0, str(Path(__file__).parents[1] / 'src'))
import redis_task_queue as q
from retry_priority import claim_retry_first


@unittest.skipUnless(os.environ.get('RETRY_TEST_REDIS_PASSWORD_FILE'), 'explicit isolated Redis integration opt-in required')
class LivePriorityTests(unittest.TestCase):
    def test_retry_then_hold_then_primary_without_production_changes(self):
        secret=Path(os.environ['RETRY_TEST_REDIS_PASSWORD_FILE']).read_text(encoding='utf-8-sig').strip()
        prefix='wechat:channels:test-retry-priority-'+uuid.uuid4().hex
        args=SimpleNamespace(redis_url='redis://127.0.0.1:6379/0', redis_password=secret,
            prefix=prefix, stream=prefix+':tasks', group='test-primary', retry_stream=prefix+':retry',
            retry_group='test-retry', consumer='test-worker-A', reclaim_idle_seconds=300, block_seconds=1)
        checkpoint_key=prefix+':video-state:topic1_test'
        keys=[args.stream,args.retry_stream,checkpoint_key]
        self.assertTrue(all(k.startswith('wechat:channels:test-retry-priority-') for k in keys))
        with q.RedisConnection(args.redis_url,secret) as connection:
            def command(url,password,*parts,**kwargs):return connection.command(*parts)
            adapter=SimpleNamespace(**{name:getattr(q,name) for name in
                ('read_new','auto_claim','pending_count','group_lag','fields_to_dict')},redis_command=command)
            from unittest.mock import patch
            try:
                with patch.object(q,'redis_command',command):
                    q.ensure_group(args.redis_url,secret,args.stream,args.group)
                    q.ensure_group(args.redis_url,secret,args.retry_stream,args.retry_group)
                    item={'task_id':'topic1:test','topic':'topic1','keyword':'isolated test','queue':{'tasks':[]}}
                    connection.command('XADD',args.stream,'*','payload',json.dumps(item))
                    connection.command('XADD',args.retry_stream,'*','payload',json.dumps({**item,'fingerprint':'fp'}))
                    connection.command('HSET',checkpoint_key,'fp',json.dumps({'status':'retry_pending'}))
                    message,hold,_=claim_retry_first(adapter,args)
                    self.assertTrue(hold);self.assertEqual(message[1]['fingerprint'],'fp')
                    self.assertEqual(q.pending_count(args.redis_url,secret,args.stream,args.group),0)
                    self.assertEqual(q.group_lag(args.redis_url,secret,args.stream,args.group),1)
                    args.consumer='test-worker-B'
                    self.assertTrue(claim_retry_first(adapter,args)[1])
                    # A failed/unfinished attempt is not ACKed and cannot unlock new work.
                    self.assertEqual(q.pending_count(args.redis_url,secret,args.retry_stream,args.retry_group),1)
                    connection.command('HSET',checkpoint_key,'fp',json.dumps({'status':'completed'}))
                    connection.command('XACK',args.retry_stream,args.retry_group,message[0])
                    # Force Redis's lag into its historical unknown form.
                    connection.command('XGROUP','SETID',args.retry_stream,args.retry_group,message[0])
                    self.assertEqual(q.group_lag(args.redis_url,secret,args.retry_stream,args.retry_group),0)
                    self.assertFalse(claim_retry_first(adapter,args)[1])
                    primary,recovered=q.claim_primary_message(args,recover_stale_pending=False)
                    self.assertIsNotNone(primary);self.assertFalse(recovered)
                    connection.command('HSET',checkpoint_key,'fp',json.dumps({'status':'dead_letter'}))
                    self.assertTrue(claim_retry_first(adapter,args)[1])
                    print(json.dumps({'isolatedRedisTest':'passed','retryFirst':True,'inflightBlocksPrimary':True,
                        'unknownLagRecovered':True,'cleanRetryAdmitsPrimary':True,'deadLetterBlocksNewKeywords':True,
                        'productionTaskChanges':False,'rpaStarted':False,'mysqlWrites':False}))
            finally:
                connection.command('UNLINK',*keys)


if __name__ == '__main__': unittest.main()
