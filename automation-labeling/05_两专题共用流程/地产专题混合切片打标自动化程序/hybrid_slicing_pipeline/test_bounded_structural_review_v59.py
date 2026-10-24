import unittest
from bounded_structural_review_v59 import review
from comment_identity_protocol_v59 import obj

class FakeRunner:
    def __init__(self,responses,status='success'):self.responses=responses;self.requests=[];self.status=status
    def call(self,system,payload,doc,phase,**kwargs):
        self.requests.append((system,payload,doc,phase,kwargs))
        return self.responses[len(self.requests)-1],{'status':self.status,'request_key':str(len(self.requests))}

class StructuralReviewTests(unittest.TestCase):
    schema=obj({'supported':{'type':'boolean'},'confidence':{'type':'number','minimum':0,'maximum':1}})
    def invoke(self,runner):return review('rules',{'source':'literal'},self.schema,{'record_id':'test'},'phase',runner)
    def test_valid_rejection_never_retried(self):
        runner=FakeRunner([{'supported':False,'confidence':.3}]);raw,calls,audit,issues=self.invoke(runner)
        self.assertFalse(raw['supported']);self.assertEqual(len(calls),1);self.assertFalse(issues)
    def test_valid_low_confidence_never_defaulted(self):
        runner=FakeRunner([{'supported':True,'confidence':.2}]);raw,_,_,_=self.invoke(runner)
        self.assertEqual(raw['confidence'],.2);self.assertEqual(len(runner.requests),1)
    def test_only_one_structural_repair_with_raw_history(self):
        runner=FakeRunner([{'supported':True},{'supported':False,'confidence':.8}])
        raw,calls,audit,issues=self.invoke(runner)
        self.assertFalse(issues);self.assertEqual(len(calls),2)
        self.assertEqual(audit[0]['raw_response'],{'supported':True})
        self.assertEqual(runner.requests[1][1]['previous_response'],{'supported':True})
        self.assertEqual(runner.requests[0][-1]['response_schema'],self.schema)
    def test_second_structural_failure_stops(self):
        runner=FakeRunner([{},{}]);raw,calls,_,issues=self.invoke(runner)
        self.assertIsNone(raw);self.assertEqual(len(calls),2);self.assertTrue(issues)
    def test_api_failure_not_semantic_retry(self):
        runner=FakeRunner([None],status='failed_http');raw,calls,_,issues=self.invoke(runner)
        self.assertIsNone(raw);self.assertEqual(len(calls),1);self.assertTrue(issues)

if __name__=='__main__':unittest.main()
