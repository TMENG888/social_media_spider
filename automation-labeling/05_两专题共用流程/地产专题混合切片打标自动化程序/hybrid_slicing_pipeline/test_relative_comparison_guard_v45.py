import unittest
import relative_comparison_guard_v45 as guard


class TurnQualifiers(unittest.TestCase):
    def setUp(self):
        self.fragment={'prose_key':'P','text':'乙认为巴士优于轮渡。'}
        self.response={'checks':[{'prose_key':'P','source_keys':['B']}]}
        self.entries=[{'source_key':'A','speaker':'乙','turn_id':2,'start':0,'text':'没听过。'},
                      {'source_key':'B','speaker':'乙','turn_id':2,'start':5,'text':'如果二选一，也许巴士好一点。'}]

    def test_preceding_qualifier_in_same_turn(self):
        self.assertTrue(guard.issues(self.fragment,self.entries,self.response))

    def test_same_nickname_later_turn_not_borrowed(self):
        self.entries[0]['turn_id']=4
        self.assertFalse(guard.issues(self.fragment,self.entries,self.response))

    def test_other_actor_not_borrowed(self):
        self.entries[0]['speaker']='甲'
        self.assertFalse(guard.issues(self.fragment,self.entries,self.response))

    def test_no_turn_id_does_not_expand_context(self):
        for e in self.entries:e.pop('turn_id')
        self.assertFalse(guard.issues(self.fragment,self.entries,self.response))

    def test_preserved_modality(self):
        self.fragment['text']='乙未听过，仅认为二选一时巴士可能好一点。'
        self.assertFalse(guard.issues(self.fragment,self.entries,self.response))

    def test_relative_preference_also_preserves_unexperienced(self):
        self.fragment['text']='乙相对倾向巴士。'
        self.assertTrue(guard.issues(self.fragment,self.entries,self.response))

    def test_unselected_turn_not_borrowed(self):
        self.response['checks'][0]['source_keys']=[]
        self.assertFalse(guard.issues(self.fragment,self.entries,self.response))

    def test_comparatively_better_keeps_experience_qualification(self):
        self.fragment['text']='乙认为二选一巴士较好。'
        self.assertTrue(guard.issues(self.fragment,self.entries,self.response))


if __name__=='__main__':unittest.main()
