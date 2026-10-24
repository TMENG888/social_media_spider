import unittest
from delivery_v82 import decision,catalogue,reconcile
class FlexibleTest(unittest.TestCase):
 def test_no_numeric_regex_veto(self):
  for text in ['面宽十二米','17米面宽','面积一百平方米']:
   raw={'verdict':'supported','confidence':.95,'source_keys':['S001'],'object_quote':text,'same_object':True,'necessary_basis_present':True,'modality_preserved':True}
   self.assertEqual(decision(raw,[],text,text,catalogue(text))[0],'supported')
 def test_api_fail_uncertain(self):self.assertEqual(decision(None,['失败'],'x','x',[])[0],'uncertain')
 def test_bad_evidence_uncertain(self):
  r={'verdict':'supported','confidence':.95,'source_keys':['BAD'],'object_quote':'房源','same_object':True,'necessary_basis_present':True,'modality_preserved':True}
  self.assertEqual(decision(r,[],'房源','房源',catalogue('房源'))[0],'uncertain')
 def test_conflict_keeps_audit_not_confirmed_tag(self):
  base={'rows':[{'unit_id':'u','标签明细':[{'标签路径ID':'VOC-0483'}],'备注':'','打标说明':'','验收状态':'自动通过'}],'traces':[{'unit_id':'u'}],'calls':[]}
  item={'unit_id':'u','tag_id':'VOC-0483','context':{'verdict':'supported','decision':{'why':'支持'},'issues':[],'calls':[]},'local':{'verdict':'unsupported','decision':{'why':'不支持'},'issues':[],'calls':[]}}
  out=reconcile(base,[item],'Hconsensus');self.assertEqual(out['rows'][0]['标签明细'],[]);self.assertTrue(out['traces'][0]['H柔性标签复核']);self.assertEqual(len(base['rows'][0]['标签明细']),1)
if __name__=='__main__':unittest.main()
