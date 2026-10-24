import copy,unittest
import local_alias_check_schema_v56 as v

class AliasSchema(unittest.TestCase):
    def setUp(self):self.check={'alias_key':'A','approved':True,'why':'实际源文承接','confidence':.95}
    def test_wrong_container_not_silently_renamed(self):
        raw={'results':[self.check]};original=copy.deepcopy(raw)
        self.assertTrue(v.validate(raw,['A'])[1]);self.assertEqual(original,raw)
    def test_duplicate_unknown_and_boolean_score_rejected(self):
        for checks,required in ([self.check,self.check],['A','B']),([dict(self.check,alias_key='X')],['A']),([dict(self.check,confidence=True)],['A']):
            self.assertTrue(v.validate({'checks':checks},required)[1])
    def test_valid_rejection_and_low_confidence_not_promoted(self):
        checks,issues=v.validate({'checks':[dict(self.check,approved=False,confidence=.4)]},['A'])
        self.assertFalse(issues);self.assertFalse(checks[0]['approved']);self.assertEqual(.4,checks[0]['confidence'])
    def test_real_format_repair_preserves_raw_and_requests_schema(self):
        bad={'results':[self.check]};good={'checks':[self.check]}
        class Runner:
            def __init__(self):self.calls=[]
            def call(self,system,payload,doc,phase,**kwargs):
                self.calls.append((copy.deepcopy(payload),kwargs));return (bad if len(self.calls)==1 else good),{'status':'success'}
        runner=Runner();out,audit,calls,issues=v.review({'text':'原文'},[],[{'alias_key':'A'}],runner,'独立核验')
        self.assertFalse(issues);self.assertEqual(2,len(runner.calls));self.assertEqual(bad,audit[0]['raw_response'])
        self.assertEqual(bad,runner.calls[1][0]['previous_response']);self.assertIn('response_schema',runner.calls[0][1])
    def test_valid_semantic_rejection_not_retried(self):
        check=dict(self.check,approved=False)
        class Runner:
            def __init__(self):self.calls=0
            def call(self,*args,**kwargs):self.calls+=1;return {'checks':[check]},{'status':'success'}
        runner=Runner();out,audit,calls,issues=v.review({'text':'原文'},[],[{'alias_key':'A'}],runner,'S')
        self.assertFalse(issues);self.assertEqual(1,runner.calls);self.assertFalse(out[0]['approved'])

if __name__=='__main__':unittest.main()
