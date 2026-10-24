import unittest
import copy
from experiment_routes_v78 import valid_labels,apply

class Tests(unittest.TestCase):
    def setUp(self):
        self.index={'D0191':{'tag_id':'VOC-0191','number':190,'l1':'产品','l2':'户型','l3':'通用',
            'l4':'采光','l5':None,'emphasis':'采光','instruction':'采光'}}
        self.result={'document':{'text':'甲项目。该户型采光好。','kind':'文章'},
            'rows':[{'unit_id':'x','原文摘录':'该户型采光好。','备注':'待核','标签明细':[]}],
            'traces':[{'起点':4,'终点':12}],'calls':[]}
        self.item={'unit_id':'x','choice_key':'D0191','property_quote':'采光好','object_quote':'甲项目',
            'confidence':.9,'why':'户型采光明示'}
    def test_context_outside_slice_allowed(self):
        a,e=valid_labels(self.result,{'checked_keys':['D0191'],'labels':[self.item]},self.index)
        self.assertEqual(len(a),1);self.assertFalse(e)
    def test_property_outside_slice_forbidden(self):
        item=dict(self.item,property_quote='甲项目')
        a,e=valid_labels(self.result,{'checked_keys':['D0191'],'labels':[item]},self.index)
        self.assertFalse(a);self.assertTrue(e)
    def test_missing_dictionary_check(self):
        a,e=valid_labels(self.result,{'checked_keys':[],'labels':[self.item]},self.index)
        self.assertFalse(a);self.assertTrue(e)
    def test_low_score_not_accepted(self):
        a,e=valid_labels(self.result,{'checked_keys':['D0191'],'labels':[dict(self.item,confidence=.89)]},self.index)
        self.assertFalse(a)
    def test_apply_preserves_source_and_dictionary(self):
        out=apply(self.result,[self.item],{},self.index,[],{},'A',[])
        self.assertEqual(out['rows'][0]['原文摘录'],self.result['rows'][0]['原文摘录'])
        self.assertEqual(out['rows'][0]['标签明细'][0]['标签路径ID'],'VOC-0191')
        self.assertEqual(self.result['rows'][0]['标签明细'],[])
    def test_failure_keeps_original_tags(self):
        out=apply(self.result,[self.item],{},self.index,[],{},'A',['failure'])
        self.assertEqual(out['rows'][0]['标签明细'],[])

if __name__=='__main__':unittest.main()
