import unittest
import comment_qualification_feedback_v57 as v
import comment_object_bindings as bindings

class QualificationFeedback(unittest.TestCase):
    def setUp(self):
        self.source='【父评论｜游客】未坐过缆车。二选一也许缆车好一点。'
        self.entries=bindings.source_catalog(self.source)
        self.fragment={'prose_key':'P','text':'游客认为缆车较好。'}
        self.response={'checks':[{'prose_key':'P','status':'supported','source_keys':[self.entries[-1]['source_key']],
            'object_binding_supported':True,'relation_supported':True,'modality_preserved':True,
            'qualifiers_preserved':True,'why':'比较','confidence':.95}], 'object_bindings':[]}
    def test_qualification_feedback_not_suppressed_by_bad_binding(self):
        okay,audit=v.verify(self.fragment,self.entries,self.response)
        self.assertFalse(okay)
        self.assertTrue(any('未体验' in issue for a in audit for issue in a.get('issues',[])))
    def test_success_history_removed_but_all_failure_issues_preserved(self):
        checks=[{'accepted':True,'why':'正确','reference_attempts':[{'large':'history'}]},
                {'accepted':False,'assertion_quote':'游客认为缆车较好。','issues':['限定缺失','对象绑定错'],
                 'why':'需要保留未体验','reference_attempts':[{'large':'history'}]}]
        out=v.compact_feedback(checks)
        self.assertEqual(1,len(out));self.assertEqual(['限定缺失','对象绑定错'],out[0]['issues'])
        self.assertNotIn('reference_attempts',out[0]);self.assertIs(out[0]['accepted'],False)
    def test_semantic_rejection_never_approved(self):
        self.response['checks'][0]['status']='unsupported'
        self.assertFalse(v.verify(self.fragment,self.entries,self.response)[0])
    def test_other_turn_not_borrowed(self):
        source='【父评论｜游客】未坐过缆车。二选一也许缆车好一点。【子评论1｜游客】渡轮实际更好。'
        entries=bindings.source_catalog(source)
        response={'checks':[dict(self.response['checks'][0],source_keys=[entries[-1]['source_key']])],'object_bindings':[]}
        okay,audit=v.verify({'prose_key':'P','text':'游客认为渡轮较好。'},entries,response)
        self.assertFalse(okay)
        self.assertFalse(any('未体验' in issue for a in audit for issue in a.get('issues',[])))

if __name__=='__main__':unittest.main()
