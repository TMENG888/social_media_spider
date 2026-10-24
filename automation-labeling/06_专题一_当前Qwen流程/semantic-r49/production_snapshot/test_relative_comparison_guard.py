import unittest
import relative_comparison_guard as guard


class RelativeComparison(unittest.TestCase):
    def setUp(self):
        self.entries=[{'source_key':'SOURCE','speaker':'乙','text':'没听过。如果轮渡和巴士二选一，也许还是巴士好一点。'}]
        self.fragment={'prose_key':'ACTUAL','text':'乙认为巴士优于轮渡。'}
        self.response={'checks':[{'prose_key':'ACTUAL','source_keys':['SOURCE']}]}

    def test_unexperienced_relative_comparison_not_absolute(self):
        self.assertTrue(guard.issues(self.fragment,self.entries,self.response))

    def test_preserved_qualifiers_not_flagged(self):
        self.fragment['text']='乙未体验，认为二选一也许巴士更好。'
        self.assertFalse(guard.issues(self.fragment,self.entries,self.response))

    def test_other_actor_not_used_as_constraint(self):
        self.fragment['text']='甲认为巴士优于轮渡。'
        self.assertFalse(guard.issues(self.fragment,self.entries,self.response))

    def test_unselected_source_not_constraint(self):
        self.response['checks'][0]['source_keys']=[]
        self.assertFalse(guard.issues(self.fragment,self.entries,self.response))

    def test_no_comparison_claim_not_flagged(self):
        self.fragment['text']='乙认为今年巴士频次减少。'
        self.assertFalse(guard.issues(self.fragment,self.entries,self.response))

    def test_actual_experience_not_forced_into_uncertainty(self):
        self.entries[0]['text']='实际体验过，两者相比巴士更好。'
        self.assertFalse(guard.issues(self.fragment,self.entries,self.response))


if __name__=='__main__':unittest.main()
