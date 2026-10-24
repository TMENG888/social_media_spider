import copy
import unittest
import comment_object_bindings as sources
import comment_binding_schema_v44 as protocol


class RootBindingSchema(unittest.TestCase):
    def setUp(self):
        self.catalog=sources.source_catalog('【父评论｜甲】南湖新城道路很堵。')
        key=self.catalog[0]['source_key'];self.fragment={'prose_key':'ACTUAL','text':'甲认为南湖新城道路拥堵。'}
        self.response={'checks':[{'prose_key':'ACTUAL','status':'supported','source_keys':[key],
            'object_binding_supported':True,'relation_supported':True,'modality_preserved':True,
            'qualifiers_preserved':True,'why':'原文对象及道路现象','confidence':.95}],
            'object_bindings':[{'prose_key':'ACTUAL','object_quote':'南湖新城','source_object_quote':'南湖新城',
                'object_source_key':key,'attribute_source_key':key,'attribute_quote':'道路很堵',
                'generic_or_unresolved':False}]}

    def test_unique_example_explicitly_has_both_root_keys(self):
        self.assertIn('两个根键checks和object_bindings必须同时返回',protocol.SYSTEM)
        self.assertEqual(1,protocol.SYSTEM.count('"checks":['))
        self.assertEqual(1,protocol.SYSTEM.count('"object_bindings":['))
        self.assertNotIn('"assertion_quote":',protocol.SYSTEM)

    def test_complete_binding_still_requires_all_semantic_dimensions(self):
        self.assertTrue(protocol.verify(self.fragment,self.catalog,self.response)[0])
        self.response['checks'][0]['modality_preserved']=False
        self.assertFalse(protocol.verify(self.fragment,self.catalog,self.response)[0])

    def test_missing_entire_root_binding_not_accepted(self):
        del self.response['object_bindings']
        self.assertFalse(protocol.verify(self.fragment,self.catalog,self.response)[0])

    def test_null_generic_flag_not_boolean(self):
        self.response['object_bindings'][0]['generic_or_unresolved']=None
        self.assertFalse(protocol.verify(self.fragment,self.catalog,self.response)[0])

    def test_explicit_object_cannot_claim_generic(self):
        self.response['object_bindings'][0]['generic_or_unresolved']=True
        self.assertFalse(protocol.verify(self.fragment,self.catalog,self.response)[0])

    def test_no_mutation_or_old_quote_retrofit(self):
        original=copy.deepcopy(self.response)
        protocol.verify(self.fragment,self.catalog,self.response)
        self.assertEqual(original,self.response)
        self.response['object_bindings'][0]['assertion_quote']='甲...拥堵'
        self.assertFalse(protocol.verify(self.fragment,self.catalog,self.response)[0])


if __name__=='__main__':unittest.main()
