import copy
import unittest
import comment_object_bindings as source
import comment_single_target_binding_protocol as protocol


class SingleTarget(unittest.TestCase):
    def test_prompt_does_not_keep_contradictory_old_binding_schema(self):
        self.assertNotIn('每项包含assertion_quote',protocol.SYSTEM)
        self.assertNotIn('"assertion_quote":"当前text逐字表述"',protocol.SYSTEM)
        self.assertNotIn('assertion_quote必须是当前待审text',protocol.SYSTEM)
        self.assertIn('禁止另造assertion_quote',protocol.SYSTEM)

    def setUp(self):
        self.text='【父评论｜Chinex】交通是短板，去西四环要经过四个红绿灯。去阜石路高架也得经过四个红绿灯。'
        self.catalog=source.source_catalog(self.text)
        self.fragment={'prose_key':'P-ACTUAL','text':'评论者指出交通是短板，去西四环和阜石路高架均需经过四个红绿灯。'}
        def binding(name):
            entry=next(e for e in self.catalog if name in e['text'])
            return {'prose_key':'P-ACTUAL','object_quote':name,'source_object_quote':name,
                    'object_source_key':entry['source_key'],'attribute_source_key':entry['source_key'],
                    'attribute_quote':entry['text'],'generic_or_unresolved':False}
        self.response={'checks':[{'prose_key':'P-ACTUAL','status':'supported',
            'source_keys':[e['source_key'] for e in self.catalog],
            'object_binding_supported':True,'relation_supported':True,'modality_preserved':True,
            'qualifiers_preserved':True,'why':'两条路线分别原文陈述四个灯，摘要没有相加次数','confidence':.95}],
            'object_bindings':[binding('西四环'),binding('阜石路高架')]}

    def test_parallel_routes_without_model_repeating_assertion(self):
        raw=copy.deepcopy(self.response)
        okay,audit=protocol.verify(self.fragment,self.catalog,self.response)
        self.assertTrue(okay);self.assertEqual(raw,self.response)
        self.assertEqual(self.fragment['text'],audit[0]['assertion_quote'])

    def test_bad_target_key_never_inferred(self):
        self.response['object_bindings'][0]['prose_key']='OTHER'
        self.assertFalse(protocol.verify(self.fragment,self.catalog,self.response)[0])

    def test_old_ellipsis_assertion_not_silently_retrofitted(self):
        self.response['object_bindings'][0]['assertion_quote']='去西四环...经过四个红绿灯'
        self.assertFalse(protocol.verify(self.fragment,self.catalog,self.response)[0])

    def test_missing_or_false_semantic_check_still_rejected(self):
        self.response['checks'][0]['relation_supported']=False
        self.assertFalse(protocol.verify(self.fragment,self.catalog,self.response)[0])

    def test_source_attribute_fabrication_still_rejected(self):
        self.response['object_bindings'][0]['attribute_quote']='道路没有红绿灯'
        self.assertFalse(protocol.verify(self.fragment,self.catalog,self.response)[0])

    def test_cross_turn_project_transfer_still_rejected(self):
        catalog=source.source_catalog('【父评论｜甲】海宸北侧可能好。【子评论1｜乙】最北侧也很吵。')
        fragment={'prose_key':'P-ACTUAL','text':'海宸北侧很吵。'}
        response=copy.deepcopy(self.response)
        response['checks'][0]['source_keys']=[e['source_key'] for e in catalog]
        response['object_bindings']=[{'prose_key':'P-ACTUAL','object_quote':'海宸北侧',
            'source_object_quote':'海宸北侧','object_source_key':catalog[0]['source_key'],
            'attribute_source_key':catalog[1]['source_key'],'attribute_quote':'最北侧也很吵',
            'generic_or_unresolved':False}]
        self.assertFalse(protocol.verify(fragment,catalog,response)[0])


if __name__=='__main__':unittest.main()
