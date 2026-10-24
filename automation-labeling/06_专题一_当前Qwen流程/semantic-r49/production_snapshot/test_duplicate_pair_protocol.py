import unittest
from duplicate_pair_protocol import response_check,different_markers,missing_pair_evidence,incomplete_pair_decision

class PairProtocol(unittest.TestCase):
    def test_malformed_claimed_duplicate_gets_one_repair(self):
        self.assertTrue(incomplete_pair_decision({'same_object':True,'same_fact':True,'keep_side':'A','confidence':None},{}))
        self.assertFalse(incomplete_pair_decision({'same_object':None,'same_fact':None},{}))
        self.assertFalse(incomplete_pair_decision({'same_object':False,'same_fact':False},{}))
    def test_other_project_cannot_be_deleted_even_if_model_says_same(self):
        raw={'same_object':True,'same_fact':True,'keep_side':'A','confidence':.95,
            'evidence_ids_a':[1],'evidence_ids_b':[1],'why':'四居相同'}
        pair={'pair_id':10,'unit_a':3,'unit_b':8}
        check=response_check(raw,pair,'【甲项目】四居。','【乙项目】四居。')
        self.assertNotEqual('same_fact',check['verdict'])
    def test_side_maps_only_the_current_pair(self):
        raw={'same_object':True,'same_fact':True,'keep_side':'B','confidence':.95,
            'evidence_ids_a':[1],'evidence_ids_b':[1],'why':'同项目同配置'}
        check=response_check(raw,{'pair_id':8,'unit_a':3,'unit_b':5},'同项目一梯一户。','同项目一梯一户。')
        self.assertEqual(5,check['keep_unit_index']);self.assertEqual('same_fact',check['verdict'])
    def test_missing_confidence_is_not_defaulted(self):
        raw={'same_object':True,'same_fact':True,'keep_side':'A','evidence_ids_a':[1],'evidence_ids_b':[1]}
        check=response_check(raw,{'pair_id':0,'unit_a':0,'unit_b':1},'同一配置','同一配置')
        self.assertEqual('uncertain',check['verdict'])
    def test_missing_evidence_requests_repair_not_deletion(self):
        raw={'same_object':True,'same_fact':True,'keep_side':'A','confidence':.95,
            'evidence_ids_a':[1],'evidence_ids_b':[],'why':'同项目同配置'}
        check=response_check(raw,{'pair_id':1,'unit_a':0,'unit_b':1},'一梯一户','一梯一户')
        self.assertEqual('uncertain',check['verdict']);self.assertTrue(missing_pair_evidence(raw,check))
    def test_different_facts_no_forced_evidence_repair(self):
        raw={'same_object':False,'same_fact':False}
        self.assertFalse(missing_pair_evidence(raw,{'quote_a':None,'quote_b':None}))

if __name__=='__main__':unittest.main()
