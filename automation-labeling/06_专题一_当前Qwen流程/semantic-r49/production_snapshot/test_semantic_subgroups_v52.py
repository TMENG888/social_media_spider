import unittest
from unittest.mock import patch
import semantic_subgroups_v52 as v

class ContinuousSubgroups(unittest.TestCase):
    def setUp(self):
        self.entries=[{'source_unit_key':k,'text':'原文'+k} for k in 'ABCDE']
        self.good={'groups':[{'start_key':'B','end_key':'C'},{'start_key':'D','end_key':'D'}]}
    def test_exact_coverage(self):
        self.assertEqual(([(1,2),(3,3)],[]),v.validate(self.good,self.entries,1,3))
    def test_drop_overlap_reorder_escape_and_whole_rejected(self):
        for pairs in [('BC',),('BC','CD'),('DD','BC'),('AC','DD'),('BD',),('BX','DD')]:
            r={'groups':[{'start_key':p[0],'end_key':p[1]} for p in pairs]}
            self.assertTrue(v.validate(r,self.entries,1,3)[1],pairs)
    def test_nested_key_rejected(self):
        self.assertTrue(v.validate({'groups':[{'start_key':['B'],'end_key':'D'}]},self.entries,1,3)[1])
    def exercise(self,result):
        good=self.good
        class Runner:
            supports_response_schema=True
            def __init__(self):self.calls=0
            def call(self,*args,**kwargs):self.calls+=1;return good,{'status':'success'}
        runner=Runner()
        with patch.object(v.recovery,'review',return_value=result) as audit:
            out,records,calls,issues=v.review({'text':'完整全文','topic':'全国地产设计产品力监测'}, {}, [],self.entries,1,3,runner,'独立审核',lambda *args:(None,[]),[])
        self.assertEqual(1,runner.calls);self.assertEqual(1,audit.call_count)
        return out
    def test_independent_rejection_retains_every_member(self):
        out=self.exercise((None,[{'semantic_rejection':True}],[],['不同对象']))
        self.assertEqual(['B','C','D'],[g['start_key'] for g in out])
        self.assertTrue(all(g['start_key']==g['end_key'] for g in out))
    def test_independent_approval_only_merges_selected_subgroup(self):
        out=self.exercise(({'kind':'same_object'},[],[],[]))
        self.assertEqual([('B','C'),('D','D')],[(g['start_key'],g['end_key']) for g in out])
    def test_invalid_proposal_has_no_independent_calls(self):
        class Runner:
            supports_response_schema=True
            def call(self,*args,**kwargs):return {'groups':[{'start_key':'B','end_key':'D'}]},{'status':'success'}
        with patch.object(v.recovery,'review') as audit:
            out,records,calls,issues=v.review({'text':'完整全文','topic':'全国地产设计产品力监测'}, {}, [],self.entries,1,3,Runner(),'S',None,[])
        audit.assert_not_called();self.assertTrue(issues)
        self.assertEqual(['B','C','D'],[g['start_key'] for g in out])

if __name__=='__main__':unittest.main()
