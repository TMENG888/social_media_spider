import unittest
import label_retention_v89 as r
class LossGuardTests(unittest.TestCase):
 def setUp(self):
  self.prior={'rows':[{'unit_id':'T2-test-V001','标签明细':[{'标签路径ID':'VOC-0094'},{'标签路径ID':'VOC-0095'}],'原始摘录':'公司上市且评级A-'}],
   'traces':[{'起点':0,'终点':9,'标签证据与理由':[{'choice_key':'D0094','direct_quote':'上市'}]}]}
 def test_only_missing_labels_are_rechecked(self):
  current={'rows':[{'unit_id':'T2-test-V001','标签明细':[{'标签路径ID':'VOC-0095'}]}],'excluded_intervals':[]}
  items=r.lost_items(self.prior,current)
  self.assertEqual([x['key'] for x in items[0]['lost_candidates']],['D0094'])
 def test_no_silent_old_label_copy(self):
  current={'rows':[],'excluded_intervals':[]};items=r.lost_items(self.prior,current)
  self.assertEqual(len(items[0]['lost_candidates']),2);self.assertEqual(current['rows'],[])
 def test_confirmed_duplicate_not_blindly_resurrected(self):
  current={'rows':[],'excluded_intervals':[{'原单元ID':'T2-test-V001'}]}
  self.assertEqual(r.lost_items(self.prior,current),[])
if __name__=='__main__':unittest.main()
