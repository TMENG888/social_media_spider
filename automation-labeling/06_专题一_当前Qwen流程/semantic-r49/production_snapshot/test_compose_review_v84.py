import copy,unittest
from compose_review_delivery_v84 import compose

class NonDestructiveReview(unittest.TestCase):
 def base(self):
  return {'results':[{'document':{'record_id':'r'},'calls':[],'rows':[{'unit_id':'u','标签明细':[{'标签路径ID':'VOC-0157'}],'观点摘要':'飞机噪音持续三五秒。','备注':'','验收状态':'自动通过'}],
   'traces':[{'unit_id':'u','校验问题':[]}],'audit':[]}]}
 def test_does_not_apply_candidate_tag_or_prose_deletion(self):
  stable=self.base();candidate=copy.deepcopy(stable);candidate['results'][0]['rows'][0].update(标签明细=[],观点摘要=None)
  candidate['results'][0]['traces'][0]['最终全标签核验']={'relevance':'relevant','prose_verdict':'unsupported','prose_reason':'测试争议'}
  result=compose(stable,candidate)[0]
  self.assertEqual(result['rows'][0]['标签明细'],stable['results'][0]['rows'][0]['标签明细'])
  self.assertEqual(result['rows'][0]['观点摘要'],'飞机噪音持续三五秒。')
  self.assertEqual(result['rows'][0]['验收状态'],'需人工审核')
  self.assertIn('VOC-0157',result['rows'][0]['备注']);self.assertTrue(result['audit'])
  self.assertEqual(stable['results'][0]['rows'][0]['验收状态'],'自动通过')
 def test_rejects_missing_candidate_unit(self):
  stable=self.base();candidate=copy.deepcopy(stable);candidate['results'][0]['rows']=[]
  with self.assertRaises(ValueError):compose(stable,candidate)

if __name__=='__main__':unittest.main()
