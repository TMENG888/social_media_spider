import unittest
from unittest.mock import patch
import final_review_v83 as f

class WholeReviewTest(unittest.TestCase):
 def setUp(self):
  self.row={'unit_id':'u','原始摘录':'这套大平层很好。','标签明细':[{'标签路径ID':'VOC-0171'}],'打标说明':'VOC-0171｜大平层就是大高','备注':'','验收状态':'自动通过','project_id':None,'项目名称':'待判断','项目角色':'其他','观点摘要':'这套大平层很好。'}
  self.base={'document':{'record_id':'r','kind':'文章','topic':f.v.p.p.base.T2,'text':self.row['原始摘录'],'parent':{'文章内容':self.row['原始摘录']}},'rows':[self.row],'traces':[{'unit_id':'u','校验问题':[]}],'calls':[],'audit':[]}
  self.taxonomy=[{'tag_id':'VOC-0171','l1':'产品','l2':'总图规划','l3':'大高','l4':None,'l5':None,'emphasis':'大高','instruction':'明确大高业态','source_number':170}]
  self.business={'projects':[{'id':'P01','name':'北京臻澐','role_detail':'本品','aliases':['臻澐']}]}
  self.check={'unit_id':'u','relevance':'relevant','relevance_reason':'住宅内容','confidence':.95,'tag_checks':[{'tag_id':'VOC-0171','verdict':'unsupported','quote':'这套大平层很好。','same_object':True,'necessary_basis_present':False,'why':'大平层不证明大高','confidence':.95}],
   'project_verdict':'uncertain','project_reason':'未提项目','project_quote':'','suggested_project_keys':[],'project_confidence':.5,'prose_verdict':'supported','prose_reason':'忠实','prose_confidence':.95,'explanation_verdict':'unsupported','explanation_reason':'误推业态'}
 def invoke(self,raw,issues=None):
  with patch.object(f,'review',return_value=(raw,[],[],issues or [])):return f.run(self.base,self.taxonomy,self.business,None)
 def test_reject_non_risky_tag_audit_preserved(self):
  r=self.invoke({'source_relevance':'relevant','source_quote':'这套大平层很好。','source_reason':'住宅','source_confidence':.95,'units':[self.check]})
  self.assertEqual(r['rows'][0]['标签明细'],[]);self.assertEqual(self.base['rows'][0]['标签明细'][0]['标签路径ID'],'VOC-0171')
  self.assertEqual(r['rows'][0]['原始摘录'],self.row['原始摘录']);self.assertTrue(r['traces'][0]['最终撤回标签'])
 def test_api_failure_keeps_rows_and_flags_review(self):
  r=self.invoke(None,['API失败']);self.assertEqual(len(r['rows']),1);self.assertEqual(len(r['rows'][0]['标签明细']),1);self.assertEqual(r['rows'][0]['验收状态'],'需人工审核')
 def test_scope_vote_preserves_original_row_and_audit(self):
  r=self.invoke({'source_relevance':'unrelated','source_quote':'这套大平层很好。','source_reason':'测试排除','source_confidence':.95,'units':[self.check]})
  self.assertEqual(len(r['rows']),1);self.assertEqual(r['audit'][0]['原文'],self.row['原始摘录']);self.assertEqual(r['rows'][0]['验收状态'],'需人工审核')
 def test_uncertainty_not_exclusion(self):
  self.check['relevance']='uncertain';self.check['tag_checks'][0]['verdict']='uncertain'
  r=self.invoke({'source_relevance':'uncertain','source_quote':'这套大平层很好。','source_reason':'待核','source_confidence':.7,'units':[self.check]})
  self.assertEqual(len(r['rows']),1);self.assertEqual(len(r['rows'][0]['标签明细']),1)
 def test_disputed_candidate_can_be_restored_with_literal_basis(self):
  self.row['原始摘录']='这是大高住宅。';self.base['document']['text']=self.row['原始摘录'];self.check['tag_checks'][0]['quote']=self.row['原始摘录']
  self.base['rows'][0]['标签明细']=[]
  self.base['H_review_checks']=[{'unit_id':'u','tag_id':'VOC-0171','context':{'verdict':'uncertain'},'local':{'verdict':'supported'}}]
  self.check['tag_checks'][0].update(verdict='supported',same_object=True,necessary_basis_present=True,confidence=.96)
  r=self.invoke({'source_relevance':'relevant','source_quote':'这套大平层很好。','source_reason':'住宅','source_confidence':.95,'units':[self.check]})
  self.assertEqual(r['rows'][0]['标签明细'][0]['标签路径ID'],'VOC-0171')
  self.assertEqual(len(r['rows'][0]['标签明细'][0]),8);self.assertEqual(r['rows'][0]['验收状态'],'需人工审核')
 def test_t1_prompt_has_national_boundary_and_no_t2_dictionary(self):
  self.base['document']['topic']=f.v.p.p.base.T1
  with patch.object(f,'review',return_value=(None,[],[],['模拟'])) as mock:
   f.run(self.base,self.taxonomy,self.business,None)
  request=mock.call_args.args[1]
  self.assertIn('全国',request['research_boundary']);self.assertEqual(request['project_dictionary'],[])

if __name__=='__main__':unittest.main()
