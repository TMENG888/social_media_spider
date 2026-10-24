import unittest
import comment_object_bindings as bindings


class BindingTests(unittest.TestCase):
    def example(self,source,prose,obj,attribute):
        entries=bindings.source_catalog(source)
        object_entry=next(e for e in entries if obj in e['text'])
        attribute_entry=next(e for e in entries if attribute in e['text'])
        item={'assertion_quote':prose,'object_quote':obj,'object_source_key':object_entry['source_key'],
              'attribute_source_key':attribute_entry['source_key'],'attribute_quote':attribute}
        return bindings.verify(prose,entries,[item])

    def test_ambiguous_flat_reply_cannot_bind_named_project(self):
        self.assertTrue(self.example('【父评论｜甲】海宸北侧未来可能较好。【子评论1｜乙】最北侧也没用，巨山路噪音大。',
            '海宸北侧有巨山路噪音。','海宸北侧','巨山路噪音大'))

    def test_same_turn_object_context_is_allowed(self):
        self.assertEqual([],self.example('【父评论｜甲】海宸北侧有一块地。这里有巨山路噪音。',
            '海宸北侧有巨山路噪音。','海宸北侧','巨山路噪音'))

    def test_same_speaker_in_later_turn_does_not_prove_continuity(self):
        self.assertTrue(self.example('【父评论｜甲】海宸北侧未来可能较好。【子评论1｜甲】最北侧噪音很大。',
            '海宸北侧噪音很大。','海宸北侧','噪音很大'))

    def test_explicit_object_in_later_turn_is_allowed(self):
        self.assertEqual([],self.example('【父评论｜甲】海宸北侧未来可能较好。【子评论1｜乙】海宸北侧噪音很大。',
            '海宸北侧噪音很大。','海宸北侧','噪音很大'))

    def test_missing_binding_is_not_a_semantic_pass(self):
        self.assertTrue(bindings.verify('道路堵。',bindings.source_catalog('道路堵。'),[]))

    def test_invalid_model_reference_types_reject_instead_of_crashing(self):
        entries=bindings.source_catalog('道路堵。')
        item={'assertion_quote':'道路堵。','object_quote':'道路','object_source_key':[],
              'attribute_source_key':entries[0]['source_key'],'attribute_quote':'堵'}
        self.assertTrue(bindings.verify('道路堵。',entries,[item]))
        item['attribute_source_key']=[]
        self.assertTrue(bindings.verify('道路堵。',entries,[item]))


if __name__=='__main__':unittest.main()
