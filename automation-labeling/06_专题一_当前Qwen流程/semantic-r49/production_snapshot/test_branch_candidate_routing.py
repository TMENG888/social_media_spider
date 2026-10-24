import unittest
from branch_candidate_routing import review_candidates, resolved_ambiguity_keys


class CandidateRouting(unittest.TestCase):
    def test_redundancy_rejection_is_proposal_not_accepted(self):
        audit={'expected_keys':['D0157'],'supported':[],
            'response':{'decisions':[{'choice_key':'D0157','status':'unsupported','why':'机场标签已覆盖，通常不重复打标'}]}}
        proposed=review_candidates(audit,{'D0157'})
        self.assertEqual({'D0157'},set(proposed))
        self.assertEqual('unsupported',proposed['D0157']['candidate_status'])
        self.assertEqual([],audit['supported'])

    def test_ambiguity_and_invalid_supported_quote_reach_verifier_not_delivery(self):
        audit={'expected_keys':['D1','D2','D3'],'supported':[{'choice_key':'D1','direct_quote':'证据'}],
            'response':{'decisions':[{'choice_key':'D1','status':'supported'},
                {'choice_key':'D2','status':'ambiguous','why':'配置明确但品牌未说'},
                {'choice_key':'D3','status':'supported','direct_quote':'未定位的首轮引文'}]}}
        self.assertEqual({'D1','D2','D3'},set(review_candidates(audit,{'D1','D2','D3'})))
        self.assertEqual(1,len(audit['supported']))

    def test_illegal_or_other_branch_key_not_imported(self):
        audit={'expected_keys':['D1'],'response':{'decisions':[{'choice_key':'BAD','status':'supported'},
            {'choice_key':'D2','status':'ambiguous'}]}}
        self.assertEqual({},review_candidates(audit,{'D1','D2'}))

    def test_malformed_nonstring_key_not_crash_or_imported(self):
        audit={'expected_keys':['D1'],'supported':[{'choice_key':{}}],
            'response':{'decisions':[{'choice_key':{},'status':'ambiguous'}]}}
        self.assertEqual({},review_candidates(audit,{'D1'}))

    def test_definitive_rejection_can_resolve_initial_ambiguity_not_missing_confidence(self):
        self.assertEqual({'D1'},resolved_ambiguity_keys([
            {'choice_key':'D1','status':'unsupported','why':'对象明确不同','confidence':.95},
            {'choice_key':'D2','status':'unsupported','why':'缺对象','confidence':None},
            {'choice_key':'D3','status':'supported','why':'待原文核验','confidence':.95}]))


if __name__=='__main__':unittest.main()
