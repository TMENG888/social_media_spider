import copy,unittest
import keyword_supplement_v94 as k
from gym_policy_v96 import INSTRUCTION,obsolete_refusal

class GymPolicyTest(unittest.TestCase):
 def setUp(self):
  self.tax=k.core.base.load_taxonomy(k.core.DEFAULT_TAXONOMY)
  self.tag=copy.deepcopy(next(t for t in self.tax if t['tag_id']=='VOC-0377'))
  self.tag['instruction']=INSTRUCTION
 def direct(self,text):
  result={'document':{'record_id':'fixture','topic':k.core.base.T1,'kind':'文章','text':text},'rows':[], 'traces':[]}
  unit={'unit_id':'fixture-M001','text':text,'start':0,'end':len(text)}
  rule=k.compile_rule('D0377',self.tag)
  return any(not k.hit_issues(h,rule,unit,result) for h in k.find_hits(unit,rule))
 def test_list(self):self.assertTrue(self.direct('会所内部功能空间有：书吧、会客厅、酒窖、雪茄吧、私宴厅、游泳池、健身房、疗愈瑜伽室。'))
 def test_simple(self):self.assertTrue(self.direct('会所设有健身房。'))
 def test_equipment(self):self.assertTrue(self.direct('会所配备跑步机和哑铃等健身器械。'))
 def test_traditional(self):self.assertTrue(self.direct('會所內部設有健身房。'))
 def test_plan(self):self.assertTrue(self.direct('规划会所内部将设置健身房。'))
 def test_industry(self):self.assertFalse(self.direct('会所工作人员讲解了健身器械的行业趋势。'))
 def test_outside(self):self.assertFalse(self.direct('会所旁边的健身房开放了。'))
 def test_separate(self):self.assertFalse(self.direct('小区设有会所和健身房。'))
 def test_other_space(self):self.assertFalse(self.direct('会所设有茶室，架空层配有健身房。'))
 def test_negative(self):self.assertFalse(self.direct('会所没有健身房。'))
 def test_question(self):self.assertFalse(self.direct('会所有健身房吗？'))
 def test_no_club(self):self.assertFalse(self.direct('项目附近健身房已开放。'))
 def test_unrelated_history(self):
  self.assertFalse(obsolete_refusal('健身房位于公园，对象不匹配'))
  self.assertTrue(obsolete_refusal('仅提及健身房，未描述具体器械设施，不满足定义'))

if __name__=='__main__':unittest.main()
