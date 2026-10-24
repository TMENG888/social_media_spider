import unittest
import copy
from unittest.mock import patch
import conservative_supplement_v79 as m

class SupplementTest(unittest.TestCase):
 def check(self,confidence=.95,supported=True,quote='地漏自动补水'):
  old={'document':{'topic':'x','text':'卫生间地漏自动补水','kind':'文章'},'rows':[{'unit_id':'u','原文摘录':'卫生间地漏自动补水','标签明细':[{'标签路径ID':'VOC-0001'}],'打标说明':'旧说明','备注':'旧备注','验收状态':'需人工审核','项目':'原项目'}],'traces':[{}],'calls':[]}
  candidate=copy.deepcopy(old);candidate['rows'][0]['标签明细'] += [{'标签路径ID':'VOC-0294'}]
  decision={'supported':supported,'confidence':confidence,'object_matches':True,'property_matches':True,'modality_preserved':True,'inference_free':True,'property_quote':quote,'object_quote':'卫生间','actual_object':'卫生间','actual_property':'地漏','why':'原文支持'}
  with patch.object(m.pipeline.p.v,'registry',return_value={'D0294':{'tag_id':'VOC-0294'}}),patch.object(m,'definitions',return_value=[{}]),patch.object(m,'review',return_value=(decision,[],[],[])),patch.object(m.pipeline.p.base,'label_json',return_value={'标签路径ID':'VOC-0294'}):
   result=m.run(old,candidate,None,None)
  self.assertEqual(old['rows'][0]['标签明细'],[{'标签路径ID':'VOC-0001'}])
  for k in ['unit_id','原文摘录','项目']:self.assertEqual(result['rows'][0][k],old['rows'][0][k])
  return result
 def test_accept(self):self.assertEqual(len(self.check()['rows'][0]['标签明细']),2)
 def test_low_confidence(self):self.assertEqual(len(self.check(.89)['rows'][0]['标签明细']),1)
 def test_unsupported(self):self.assertEqual(len(self.check(supported=False)['rows'][0]['标签明细']),1)
 def test_missing_literal_evidence(self):self.assertEqual(len(self.check(quote='并不存在')['rows'][0]['标签明细']),1)

if __name__=='__main__':unittest.main()
