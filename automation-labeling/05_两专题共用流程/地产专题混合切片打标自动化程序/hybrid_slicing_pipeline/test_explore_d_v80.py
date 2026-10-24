import unittest
from explore_d_v80 import catalogue,gate

class GateTest(unittest.TestCase):
 def raw(self):
  return {'supported':True,'confidence':.95,'object_keys':['S001'],'property_keys':['S001'],'qualifier_keys':['S001'],
   **{k:True for k in ('object_matches','property_matches','same_object','modality_preserved','no_inference','necessary_attribute_present')}}
 def test_catalog_roundtrip(self):
  text='【甲】230㎡。\n【乙】毛坯总价2000万！';cat=catalogue(text)
  self.assertEqual(''.join(x['text'] for x in cat),text)
  for x in cat:self.assertEqual(text[x['start']:x['end']],x['text'])
 def test_price_without_decoration(self):self.assertFalse(gate({'tag_id':'VOC-0483'},'价格2000万',self.raw(),catalogue('价格2000万'))[0])
 def test_price_with_decoration(self):self.assertTrue(gate({'tag_id':'VOC-0483'},'精装总价2000万',self.raw(),catalogue('精装总价2000万'))[0])
 def test_marketing_tech(self):self.assertFalse(gate({'tag_id':'VOC-0232'},'科技住宅',self.raw(),catalogue('科技住宅'))[0])
 def test_marketing_villa(self):self.assertFalse(gate({'tag_id':'VOC-0168'},'255平墅',self.raw(),catalogue('255平墅'))[0])
 def test_actual_villa(self):self.assertTrue(gate({'tag_id':'VOC-0168'},'联排住宅',self.raw(),catalogue('联排住宅'))[0])
 def test_invalid_key(self):
  r=self.raw();r['property_keys']=['NO'];self.assertFalse(gate({'tag_id':'VOC-0186'},'240㎡',r,catalogue('240㎡'))[0])
 def test_object_mismatch(self):
  r=self.raw();r['same_object']=False;self.assertFalse(gate({'tag_id':'VOC-0186'},'240㎡',r,catalogue('240㎡'))[0])
 def test_confidence_boundary(self):
  r=self.raw();r['confidence']=.9;self.assertTrue(gate({'tag_id':'VOC-0186'},'240㎡',r,catalogue('240㎡'))[0]);r['confidence']=.899;self.assertFalse(gate({'tag_id':'VOC-0186'},'240㎡',r,catalogue('240㎡'))[0])

if __name__=='__main__':unittest.main()
