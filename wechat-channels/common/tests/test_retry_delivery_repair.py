import hashlib
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0,str(Path(__file__).parents[1]/'src'))
import redis_task_queue as q
import retry_delivery_repair as repair

class OriginalDeliveryRepairTests(unittest.TestCase):
    def setUp(self):
        self.args=SimpleNamespace(prefix='fixture',retry_stream='fixture:retry',retry_group='workers',
                                  retry_seeded_key='fixture:seeded',consumer='exact-repair-owner',redis_url='',redis_password=None)
        self.item={'task_id':'original','source_task_id':'original','fingerprint':'fp','topic':'topic','keyword':'原词'}
        self.retry_id=hashlib.sha256(b'original|fp').hexdigest()
        self.cp={'status':'completed','retry_count':4,'row':{'video_content':'字幕来自Amara.org'}}
        self.budget={'state':'accepted','messageId':'10-0','attempts':3,'maxAttempts':3}
        self.payload={**self.item,'retry_id':self.retry_id}
        self.history=None;self.pending=[];self.cursor='10-0';self.calls=[]
        self.query=SimpleNamespace(safe_token=q.safe_token,fields_to_dict=q.fields_to_dict,
           coverage_collect_comments=lambda item:False,redis_command=self.read,RedisError=q.RedisError)
    def read(self,url,password,*parts):
        self.calls.append(parts)
        if parts[0]=='HGET':
            if parts[1].endswith(':video-state:original'): return json.dumps(self.cp)
            if parts[1].endswith(':video-retry-budget'): return json.dumps(self.budget) if self.budget else None
            if parts[1].endswith(':original-delivery-correction-history'): return self.history
        if parts[0]=='SISMEMBER': return 1
        if parts[0]=='XRANGE': return [['10-0',['retry_id',self.retry_id,'payload',json.dumps(self.payload)]]]
        if parts[0]=='XPENDING': return self.pending
        if parts[0]=='XINFO': return [['name','workers','last-delivered-id',self.cursor]]
        raise AssertionError('Unexpected mutation/read '+str(parts[0]))
    def preview(self,**kwargs):
        return repair.restore_original_delivery(self.query,self.args,self.item,'10-0',policy=repair.POLICY,**kwargs)
    def test_preview_is_readonly_and_preserves_maximum_known_history(self):
        result=self.preview();self.assertFalse(result['applied']);self.assertEqual(result['knownAttemptsBaseline'],4)
        self.assertTrue(result['noNewStreamEntry']);self.assertEqual(result['extraAttemptLimit'],1)
        self.assertNotIn('EVAL',[c[0] for c in self.calls])
    def test_legacy_history_is_not_invented_or_reported_as_known(self):
        self.budget=None;result=self.preview()
        self.assertTrue(result['legacyAttemptsUnknown']);self.assertEqual(result['knownAttemptsBaseline'],4)
    def test_pending_original_cannot_be_duplicated_or_stolen(self):
        self.pending=[['10-0','other-owner',100,1]]
        with self.assertRaisesRegex(ValueError,'STILL_PENDING'): self.preview(apply=True)
    def test_unread_or_mismatched_original_cannot_be_reopened(self):
        self.cursor='9-0'
        with self.assertRaisesRegex(ValueError,'NOT_CONSUMED'): self.preview(apply=True)
        self.cursor='10-0';self.payload['fingerprint']='other'
        with self.assertRaisesRegex(ValueError,'IDENTITY_MISMATCH'): self.preview(apply=True)
    def test_healthy_or_explicit_skip_cannot_be_silently_reopened(self):
        for cp in [{'status':'completed'},{'status':'skipped_unresolved','row':self.cp['row']}]:
            self.cp=cp
            with self.assertRaisesRegex(ValueError,'KNOWN_BAD_TERMINAL'): self.preview(apply=True)
    def test_budget_and_one_time_ledger_cannot_be_reset(self):
        self.budget['state']='blocked'
        with self.assertRaisesRegex(ValueError,'PRIOR_ACCEPTED_BUDGET'): self.preview(apply=True)
        self.budget['state']='accepted';self.history='prior'
        with self.assertRaisesRegex(ValueError,'ALREADY_RECORDED'): self.preview(apply=True)
    def test_invalid_attempts_and_absent_optin_refused(self):
        self.cp['retry_count']=-1
        with self.assertRaisesRegex(ValueError,'ATTEMPT_HISTORY_INVALID'): self.preview(apply=True)
        with self.assertRaisesRegex(ValueError,'EXPLICIT_POLICY'): repair.restore_original_delivery(self.query,self.args,self.item,'10-0')

if __name__=='__main__': unittest.main()
