import copy,unittest
import shared_mechanism_protocol_v58 as p
import test_shared_mechanism_evidence_v57 as fixtures

class Runner:
    def __init__(self,responses):self.responses=responses;self.calls=[]
    def call(self,system,payload,doc,phase,**kwargs):
        self.calls.append((payload,phase));return self.responses[len(self.calls)-1],{'status':'success'}

class MechanismProtocol(unittest.TestCase):
    def setUp(self):
        f=fixtures.SharedMechanismEvidence();f.setUp();self.good=f.good;self.entries=f.entries
    def test_actual_long_reason_repaired_once_even_if_scalars_reject(self):
        raw=copy.deepcopy(self.good);raw.update(same_specific_system=False,why='思考'*200)
        runner=Runner([raw,self.good]);out,audit,calls,issues=p.review({'text':'全文'},self.entries,0,2,runner,lambda r:[])
        self.assertFalse(issues);self.assertIsNotNone(out);self.assertEqual(2,len(calls))
        self.assertEqual(raw,audit[0]['raw_mechanism_proof']);self.assertIn('protocol_issues',runner.calls[1][0])
    def test_valid_semantic_rejection_not_retried(self):
        raw=copy.deepcopy(self.good);raw.update(same_specific_system=False,why='独立系统，不能合并。')
        runner=Runner([raw]);out,audit,calls,issues=p.review({'text':'全文'},self.entries,0,2,runner,lambda r:[])
        self.assertIsNone(out);self.assertTrue(issues);self.assertEqual(1,len(calls))
    def test_invalid_second_response_cannot_be_silently_fixed(self):
        raw=copy.deepcopy(self.good);raw['why']='思考'*200
        runner=Runner([raw,raw]);out,audit,calls,issues=p.review({'text':'全文'},self.entries,0,2,runner,lambda r:[])
        self.assertIsNone(out);self.assertTrue(issues);self.assertEqual(2,len(calls));self.assertEqual(raw['why'],audit[-1]['raw_mechanism_proof']['why'])
    def test_low_confidence_valid_structure_not_retried(self):
        raw=copy.deepcopy(self.good);raw['confidence']=.89
        runner=Runner([raw]);self.assertIsNone(p.review({'text':'全文'},self.entries,0,2,runner,lambda r:[])[0])
        self.assertEqual(1,len(runner.calls))
    def test_nested_missing_field_is_format_violation_even_on_rejection(self):
        raw=copy.deepcopy(self.good);raw['same_specific_system']=False
        key=next(iter(raw['member_assertions']));del raw['member_assertions'][key]['confidence']
        runner=Runner([raw,self.good]);out,audit,calls,issues=p.review({'text':'全文'},self.entries,0,2,runner,lambda r:[])
        self.assertIsNotNone(out);self.assertFalse(issues);self.assertEqual(2,len(calls))
        self.assertEqual(raw,audit[0]['raw_mechanism_proof'])
    def test_nested_low_confidence_is_not_format_failure(self):
        raw=copy.deepcopy(self.good);key=next(iter(raw['member_assertions']))
        raw['member_assertions'][key]['confidence']=.89
        runner=Runner([raw]);out,audit,calls,issues=p.review({'text':'全文'},self.entries,0,2,runner,lambda r:[])
        self.assertIsNone(out);self.assertEqual(1,len(calls));self.assertTrue(issues)

if __name__=='__main__':unittest.main()
