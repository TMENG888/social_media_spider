import copy
import unittest
import comment_key_only_attribute_protocol_v47 as protocol


class KeyOnlyAttributeBinding(unittest.TestCase):
    def setUp(self):
        self.fragment={'prose_key':'P','text':'甲认为A比B声音大。'}
        self.entries=[{'source_key':'S','text':'【父评论｜甲】A比B声音大','speaker':'甲','turn_id':1,'start':0}]
        self.response={'checks':[{'prose_key':'P','status':'supported','source_keys':['S'],
            'object_binding_supported':True,'relation_supported':True,'modality_preserved':True,
            'qualifiers_preserved':True,'why':'相同发言者明确比较两对象','confidence':.95}],
            'object_bindings':[{'prose_key':'P','object_quote':obj,'source_object_quote':obj,
                'object_source_key':'S','attribute_source_key':'S'} for obj in ('A','B')]}

    def test_actual_source_owned_and_input_unmodified(self):
        original=copy.deepcopy(self.response)
        okay,audit=protocol.verify(self.fragment,self.entries,self.response)
        self.assertTrue(okay);self.assertEqual(original,self.response)
        self.assertEqual('program-literal-source-key',audit[0]['attribute_evidence_owner'])

    def test_legacy_fake_quote_not_repaired(self):
        self.response['object_bindings'][0]['attribute_quote']='比...声音大'
        self.assertFalse(protocol.verify(self.fragment,self.entries,self.response)[0])

    def test_unknown_key_or_fake_object_rejected(self):
        for field,value in [('attribute_source_key','UNKNOWN'),('object_quote','C')]:
            r=copy.deepcopy(self.response);r['object_bindings'][0][field]=value
            self.assertFalse(protocol.verify(self.fragment,self.entries,r)[0])

    def test_semantic_failure_cannot_be_overridden_by_legal_keys(self):
        self.response['checks'][0]['relation_supported']=False
        self.assertFalse(protocol.verify(self.fragment,self.entries,self.response)[0])

    def test_cross_turn_object_without_restatement_rejected(self):
        self.entries.append({'source_key':'OTHER','text':'声音大','speaker':'甲','turn_id':2,'start':20})
        self.response['object_bindings'][0]['attribute_source_key']='OTHER'
        self.assertFalse(protocol.verify(self.fragment,self.entries,self.response)[0])

    def test_old_null_object_false_flag_not_silently_fixed(self):
        self.response['object_bindings'][0]['generic_or_unresolved']=False
        self.assertFalse(protocol.verify(self.fragment,self.entries,self.response)[0])

    def test_relative_location_not_evidence_of_joint_noise(self):
        self.fragment['text']='A与B均受飞机噪音影响。'
        self.entries[0]['text']='A与B在机场两侧'
        self.assertFalse(protocol.verify(self.fragment,self.entries,self.response)[0])


if __name__=='__main__':unittest.main()
