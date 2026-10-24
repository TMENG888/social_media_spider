import unittest
from continuity_edge_scope_recovery import filter_valid


class EdgeScopeRecoveryTests(unittest.TestCase):
    entries=[{'edge_key':f'K{i}'} for i in range(3)]
    def merge(self,theme='floorplan'):return {'decision':'same_object','theme':theme}
    def test_invalid_contact_merge_does_not_discard_valid_floorplan_decision(self):
        plan={'units':[{'relevant':True}]*3+[{'relevant':False}]}
        decisions={'K0':self.merge(),'K1':{'decision':'keep'},'K2':self.merge('intro')}
        valid,issues=filter_valid(plan,self.entries,decisions)
        self.assertEqual({'K0','K1'},set(valid));self.assertEqual('K2',issues[0]['edge_key'])
        self.assertEqual('same_object',decisions['K2']['decision'])
    def test_transitive_theme_conflict_requests_all_chain_edges(self):
        plan={'units':[{'relevant':True}]*4}
        valid,issues=filter_valid(plan,self.entries,{'K0':self.merge(),'K1':self.merge('education'),'K2':{'decision':'keep'}})
        self.assertEqual({'K2'},set(valid));self.assertEqual({'K0','K1'},{x['edge_key'] for x in issues})
    def test_missing_decision_is_not_bridged_or_defaulted(self):
        plan={'units':[{'relevant':True}]*4}
        valid,issues=filter_valid(plan,self.entries,{'K0':self.merge(),'K2':self.merge('education')})
        self.assertEqual({'K0','K2'},set(valid));self.assertFalse(issues)
    def test_same_object_conflict_does_not_become_comparison_automatically(self):
        plan={'units':[{'relevant':True,'project_name':'甲'},{'relevant':True,'project_name':'乙'}]}
        valid,issues=filter_valid(plan,self.entries[:1],{'K0':self.merge()})
        self.assertFalse(valid);self.assertTrue(issues)


if __name__=='__main__':unittest.main()
