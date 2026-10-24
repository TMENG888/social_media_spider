import copy,unittest
from unittest.mock import patch
import inventory_continuity_candidates_v55 as v

class ExplicitRestatements(unittest.TestCase):
    def setUp(self):
        self.entries=[{'source_unit_key':k,'text':'原文'+k} for k in 'ABCDE']
        self.ledger={'members':{'D':{'relation':'restatement','confidence':.95,'related_source_keys':['B']},
                                'E':{'relation':'correction','confidence':.95,'related_source_keys':['A']}}}
        self.groups=[{'start_key':'A','end_key':'B','kind':'same_object'},
                     {'start_key':'C','end_key':'C','kind':'singleton'},
                     {'start_key':'D','end_key':'D','kind':'singleton'},
                     {'start_key':'E','end_key':'E','kind':'singleton'}]
    def test_only_explicit_model_relations_propose_ranges(self):
        self.assertEqual([(1,3),(0,4)],v.candidates(self.ledger,self.entries))
        self.ledger['members']['D']['relation']='continuation'
        self.assertEqual([(0,4)],v.candidates(self.ledger,self.entries))
    def test_low_confidence_and_forward_relation_not_proposal(self):
        self.ledger['members']['D']['confidence']=.5
        self.ledger['members']['E']['related_source_keys']=['E','X']
        self.assertFalse(v.candidates(self.ledger,self.entries))
    def test_rejection_retains_every_original_group_and_intervening_text(self):
        baseline={'post_split_raw_group_protocol':{'groups':self.groups}}
        original=copy.deepcopy(baseline)
        with patch.object(v.mechanism_proof,'review',return_value=(None,[],[],['不同系统'])) as check,\
             patch.object(v.ranges,'apply',side_effect=lambda doc,plan,seg,response:(response,[])):
            out,audit,calls,issues=v.review({}, {}, [],self.entries,self.ledger,baseline,object())
        self.assertFalse(issues);self.assertEqual(original,baseline);self.assertEqual(self.groups,out['groups'])
        self.assertEqual((0,3),check.call_args_list[0].args[2:4])
        self.assertEqual((0,4),check.call_args_list[1].args[2:4])
    def test_approval_does_not_skip_intervening_bridge(self):
        baseline={'post_split_raw_group_protocol':{'groups':self.groups}}
        with patch.object(v.mechanism_proof,'review',side_effect=[({'kind':'same_object'},[],[],[]),(None,[],[],['另一个系统'])]),\
             patch.object(v.ranges,'apply',side_effect=lambda doc,plan,seg,response:(response,[])):
            out,audit,calls,issues=v.review({}, {}, [],self.entries,self.ledger,baseline,object())
        self.assertFalse(issues);self.assertEqual([('A','D'),('E','E')],[(g['start_key'],g['end_key']) for g in out['groups']])

if __name__=='__main__':unittest.main()
