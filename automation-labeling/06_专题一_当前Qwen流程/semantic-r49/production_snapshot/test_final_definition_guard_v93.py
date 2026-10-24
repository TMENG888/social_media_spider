import unittest
from final_definition_guard_v92 import final_scope_risks


class FinalObjectScopeTests(unittest.TestCase):
    index={'D0373':{'l1':'产品','l3':'会所'},'D0403':{'l1':'产品','l3':'社区景观'},
        'D0168':{'l1':'产品','l3':'别墅'}}

    def risks(self,key,quote,context=''):
        return final_scope_risks({'key':key,'quotes':[quote],
            'context_quotes':[context] if context else []},self.index)

    def test_home_sample_is_not_clubhouse_style(self):
        self.assertTrue(self.risks('D0373','275㎡样板间，原木风搭配的浅色系石材形成主基调。'))

    def test_grounded_clubhouse_context_is_allowed(self):
        self.assertFalse(self.risks('D0373','样板间采用原木风。','会所样板间开放。'))

    def test_clubhouse_area_is_not_landscape_area(self):
        self.assertTrue(self.risks('D0403','社区自带约3600㎡下沉式高端会所，打造三园十八景王府园林。'))

    def test_chinese_clubhouse_area_is_also_flagged(self):
        self.assertTrue(self.risks('D0403','社区有三千六百平方米高端会所，旁边有园林。'))

    def test_explicit_landscape_area_not_held(self):
        self.assertFalse(self.risks('D0403','3600㎡会所，景观面积约5000平方米。'))
        self.assertFalse(self.risks('D0403','3600㎡会所，5000㎡花园。'))

    def test_chinese_landscape_measure_not_held(self):
        self.assertFalse(self.risks('D0403','景观面积三千平方米。'))

    def test_residential_does_not_prove_villa(self):
        self.assertTrue(self.risks('D0168','项目规划：住宅、会所，建筑面积约134㎡-275㎡。'))

    def test_explicit_villa_subtype_remains_allowed(self):
        self.assertFalse(self.risks('D0168','住宅业态为叠拼别墅。'))
        self.assertFalse(self.risks('D0168','住宅采用联排布局。'))


if __name__=='__main__':unittest.main()
