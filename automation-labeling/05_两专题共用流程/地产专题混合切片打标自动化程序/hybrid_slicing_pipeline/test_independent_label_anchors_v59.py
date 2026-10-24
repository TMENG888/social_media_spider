import unittest
from evaluate_independent_label_anchors_v59 import evaluate

class AnchorEvaluationTests(unittest.TestCase):
    def setUp(self):
        self.ref={'reference_type':'limited','anchors':[{'record_id':'A','quote':'面积100㎡',
            'required':['area'],'forbidden':['room_area'],'basis':'whole house'}]}
        self.data={'results':[{'document':{'record_id':'A','text':'面积100㎡。'},
            'rows':[{'unit_id':'A-1','原文摘录':'面积100㎡。','标签明细':[{'标签路径ID':'area'}]}]}]}
    def test_empty_result_is_missing_not_perfect(self):
        r=evaluate({'results':[]},self.ref)
        self.assertEqual(r['unprocessed_anchors'],1);self.assertIsNone(r['processed_positive_anchor_recall'])
    def test_supported_and_forbidden_count_separately(self):
        self.data['results'][0]['rows'][0]['标签明细'].append({'标签路径ID':'room_area'})
        r=evaluate(self.data,self.ref)
        self.assertEqual(r['hit_required_tags'],1);self.assertEqual(r['forbidden_tag_hits'],1)
    def test_no_rows_is_a_miss_not_excluded_success(self):
        self.data['results'][0]['rows']=[];r=evaluate(self.data,self.ref)
        self.assertEqual(r['missed_required_tags'],1)
    def test_invalid_reference_not_accuracy_evidence(self):
        self.ref['anchors'][0]['quote']='not in source';r=evaluate(self.data,self.ref)
        self.assertTrue(r['reference_errors']);self.assertIsNone(r['processed_positive_anchor_recall'])
    def test_reviewed_equivalent_restatement_can_keep_duplicate_label(self):
        self.ref['anchors'][0]['equivalent_quotes']=['同户型100㎡']
        self.data['results'][0]['document']['text']+='同户型100㎡。'
        self.data['results'][0]['rows'][0]['标签明细']=[]
        self.data['results'][0]['rows'].append({'unit_id':'A-2','原文摘录':'同户型100㎡。','标签明细':[{'标签路径ID':'area'}]})
        self.assertEqual(evaluate(self.data,self.ref)['hit_required_tags'],1)

if __name__=='__main__':unittest.main()
