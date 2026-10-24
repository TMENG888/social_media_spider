import unittest, copy
import completeness_v89 as v
from structured_response_validation_v58 import issues
class CompletenessTests(unittest.TestCase):
 def setUp(self):
  self.doc={'topic':v.base.T2,'kind':'文章','text':'安澜北京距地铁13号线上地站约1.2公里。','record_id':'T2-test'}
  self.item={'unit_id':'T2-test-V001','text':self.doc['text']}
  self.tag={'key':'D0142','quotes':['地铁13号线上地站约1.2公里'],'context_quotes':['安澜北京'],'object':'安澜北京','reason':'原文明示地铁站及距离','confidence':.95}
  self.unit={'unit_id':self.item['unit_id'],'decision':'supported','reason':'区位配套属于专题二','duplicate_of':None,'labels':[self.tag],
   'rewrite':'安澜北京距地铁13号线上地站约1.2公里。','identity':{'brand':None,'entity':None,'project_name':None,'city':None,'quotes':[]},
   'project_refs':[],'expressions':['事实介绍'],'emotions':['无态度'],'confidence':.95}
 def test_schema_no_shared_enum_contamination(self):
  self.assertFalse(issues({'units':[self.unit]},v.schema()))
 def test_grounded_subway_not_rejected_for_not_housing(self):
  self.assertEqual(v.validate_units({'units':[self.unit]},[self.item],self.doc,{'D0142':{}}),[])
 def test_bad_quote_is_format_error(self):
  self.unit['labels'][0]['quotes']=['地铁……1.2公里']
  self.assertTrue(any('证据格式' in e for e in v.validate_units({'units':[self.unit]},[self.item],self.doc,{'D0142':{}})))
 def test_false_empty_supported_is_blocked(self):
  self.unit['labels']=[]
  self.assertTrue(v.validate_units({'units':[self.unit]},[self.item],self.doc,{'D0142':{}}))
 def test_incomplete_source_is_revisited(self):
  self.doc['text']='想去看看'
  self.assertEqual(v.targets({'document':self.doc,'rows':[],'traces':[]})[0]['text'],'想去看看')
 def test_missing_summary_triggers_only_target(self):
  row={'标签明细':[{'标签路径ID':'VOC-0142'}],'打标说明':'已有理由','观点摘要':'','project_id':['C02'],'原始摘录':self.doc['text']}
  self.assertIn('无做法/摘要',v.problems(row,self.doc))
 def test_semantic_false_must_not_enter_complete_table(self):
  ck={'scope_ok':True,'confidence':.95,'labels':[{'key':'D0142','support':False,'confidence':.99}]}
  self.assertTrue(v.gated(self.unit,ck,self.item,{'D0142':{}}))
 def test_dictionary_gap_not_passed_as_complete(self):
  self.unit['decision']='dictionary_gap';self.unit['labels']=[]
  self.assertTrue(v.gated(self.unit,{'scope_ok':True,'confidence':.95,'labels':[]},self.item,{}))
 def test_unknown_new_label_blocked(self):
  self.assertTrue(v.validate_units({'units':[self.unit]},[self.item],self.doc,{}))
 def test_unique_id_alias_only(self):
  self.tag['key']='VOC-0142';v.normalize_keys({'units':[self.unit]},{'D0142':{}})
  self.assertEqual(self.tag['key'],'D0142')
 def test_format_only_quote_repair_keeps_original_decimal(self):
  self.tag['quotes']=['地铁13号线上地站 约1.2公里'];audit=[]
  v.restore_format_quotes({'units':[self.unit]},self.doc,[self.item],audit)
  self.assertEqual(self.tag['quotes'],['地铁13号线上地站约1.2公里']);self.assertEqual(len(audit),1)
 def test_numeric_lexical_change_never_restored(self):
  self.tag['quotes']=['地铁13号线上地站约12公里'];audit=[]
  v.restore_format_quotes({'units':[self.unit]},self.doc,[self.item],audit)
  self.assertEqual(audit,[]);self.assertTrue(v.validate_units({'units':[self.unit]},[self.item],self.doc,{'D0142':{}}))
 def test_outside_scope_false_is_not_review_failure(self):
  self.unit.update(decision='no_label',labels=[])
  self.assertTrue(v.confirmed_no_label(self.unit,{'scope_ok':False,'confidence':.95,'missed_keys':[]}))
 def test_missed_labels_prevent_no_label_exclusion(self):
  self.unit.update(decision='no_label',labels=[])
  self.assertFalse(v.confirmed_no_label(self.unit,{'scope_ok':False,'confidence':.95,'missed_keys':['D0142']}))
if __name__=='__main__':unittest.main()
