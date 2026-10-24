import unittest
import label_target_binding_v59 as v

class TargetBindingTests(unittest.TestCase):
    def setUp(self):
        self.text='入口大门采用拱形门廊。'
        keys=[v.source_catalog(self.text)[0]['source_key']]
        self.response={'status':'supported','actual_object':'入口大门','actual_property':'拱形门廊',
            'object_keys':keys,'property_keys':keys,'object_supported':True,'property_supported':True,
            'modality_preserved':True,'inference_free':True,'why':'对象和风格形态均有明示','confidence':.95}
    def test_supported_literal_object_and_property(self):self.assertTrue(v.verify(self.text,self.response)[0])
    def test_wrong_object_not_accepted_despite_same_style_word(self):
        self.response['object_supported']=False
        self.assertFalse(v.verify(self.text,self.response)[0])
    def test_industry_inference_not_accepted(self):
        self.response['inference_free']=False
        self.assertFalse(v.verify(self.text,self.response)[0])
    def test_valid_semantic_rejection_stays_rejected(self):
        self.response['status']='unsupported'
        self.assertFalse(v.verify(self.text,self.response)[0])
    def test_unknown_reference_not_replaced(self):
        self.response['object_keys']=['SRC-not-in-source']
        self.assertFalse(v.verify(self.text,self.response)[0])
    def test_missing_judgment_not_defaulted(self):
        self.response.pop('inference_free')
        self.assertFalse(v.verify(self.text,self.response)[0])
    def test_low_confidence_not_accepted(self):
        self.response['confidence']=.89
        self.assertFalse(v.verify(self.text,self.response)[0])

if __name__=='__main__':unittest.main()
