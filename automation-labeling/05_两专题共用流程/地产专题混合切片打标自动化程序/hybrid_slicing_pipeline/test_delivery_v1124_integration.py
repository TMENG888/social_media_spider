"""Real production wiring and bounded calls; not semantic accuracy evidence."""
import unittest
from unittest.mock import Mock
import delivery_v11 as v


class FocusedRecoveryIntegration(unittest.TestCase):
    def test_failed_comment_prose_gets_source_only_atoms_and_independent_audit(self):
        runner=Mock();runner.call.side_effect=[
            ({'supported':False},{'status':'success'}),
            ({'claims':[{'actor_quote':'甲','object_quote':None,'claim':'甲认为问题不大。',
                         'evidence_keys':[v.focused_refs.catalog('【父评论｜甲】还好问题不大')[0]['source_key']],'confidence':.95}]},{'status':'success'}),
            ({'summary':'甲认为问题不大。','supported':True,'confidence':.95},{'status':'success'}),
            ({'checks':[{'prose_key':v.prose_review.prose_catalog('甲认为问题不大。')[0]['prose_key'],
                         'status':'supported','source_keys':[v.focused_refs.catalog('【父评论｜甲】还好问题不大')[0]['source_key']],
                         'why':'保持甲的评价','confidence':.95}],
              'coverage':{'captures_primary_points':True,'source_keys':[v.focused_refs.catalog('【父评论｜甲】还好问题不大')[0]['source_key']],
                          'why':'保留问题不大的主要评价','confidence':.95}},{'status':'success'}),
            ({'checks':[{'prose_key':v.prose_review.prose_catalog('甲认为问题不大。')[0]['prose_key'],
                         'status':'supported','source_keys':[v.focused_refs.catalog('【父评论｜甲】还好问题不大')[0]['source_key']],
                         'object_binding_supported':True,'relation_supported':True,
                         'modality_preserved':True,'qualifiers_preserved':True,'why':'同一评论者完整评价','confidence':.95}],
              'object_bindings':[{'prose_key':v.prose_review.prose_catalog('甲认为问题不大。')[0]['prose_key'],
                                  'object_quote':None,'source_object_quote':None,'object_source_key':None,
                                  'attribute_source_key':v.focused_refs.catalog('【父评论｜甲】还好问题不大')[0]['source_key'],
                                  }]},{'status':'success'})]
        result=v.independent_prose_review({'topic':v.p.base.T2,'kind':'评论'},
            {'summary':None,'labels':[]},'【父评论｜甲】还好问题不大','错误父文项目',runner)
        self.assertEqual('甲认为问题不大。',result[0]['summary']);self.assertFalse(result[3])
        self.assertEqual(5,runner.call.call_count)
        for call in runner.call.call_args_list[1:]:
            self.assertNotIn('错误父文项目',str(call.args[1]))
        self.assertEqual('',runner.call.call_args_list[-2].args[1]['identity_context'])
        self.assertEqual('【父评论｜甲】还好问题不大',runner.call.call_args_list[-1].args[1]['source_text'])
    def test_failed_atom_protocol_is_bounded_and_not_original_copy(self):
        runner=Mock();runner.call.return_value=({}, {'status':'success'})
        result=v.independent_prose_review({'topic':v.p.base.T2,'kind':'评论'},
            {'summary':None,'labels':[]},'贵，真的买不起','',runner)
        self.assertIsNone(result[0]['summary']);self.assertTrue(result[3])
        self.assertEqual(5,runner.call.call_count)
    def test_atom_generation_not_accepted_without_independent_audit(self):
        runner=Mock();runner.call.side_effect=[
            ({'supported':False},{'status':'success'}),
            ({'claims':[{'actor_quote':None,'object_quote':None,'claim':'觉得贵',
                         'evidence_keys':[v.focused_refs.catalog('太贵了')[0]['source_key']],'confidence':.95}]},{'status':'success'}),
            ({'summary':'评论者认为价格很高。','supported':True,'confidence':.99},{'status':'success'}),
            ({'checks':[]},{'status':'success'}),
            ({'summary':'评论者认为价格很高。','supported':True,'confidence':.99},{'status':'success'}),
            ({'checks':[]},{'status':'success'})]
        result=v.independent_prose_review({'topic':v.p.base.T2,'kind':'评论'},
            {'summary':None,'labels':[]},'太贵了','',runner)
        self.assertIsNone(result[0]['summary']);self.assertTrue(result[3])
        self.assertEqual(6,runner.call.call_count)


if __name__=='__main__':unittest.main()
