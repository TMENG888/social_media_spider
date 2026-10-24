import unittest
from out_of_topic_scope import confirmed_outside,T1,T2


class TopicScope(unittest.TestCase):
    def inputs(self):
        scope={'content_kind':'project_environment','confidence':.95}
        review={'exclude':False,'positive_facts':[{'kind':'project_environment',
            'fact':'周边三甲医院','why':'明确外部医疗配套','evidence_ids':[1],'confidence':.95}]}
        return scope,review
    def test_environment_not_product_unit(self):
        s,r=self.inputs();self.assertTrue(confirmed_outside(s,r,{1},T1))
    def test_environment_allowed_in_topic_two(self):
        s,r=self.inputs();self.assertFalse(confirmed_outside(s,r,{1},T2))
    def test_mixed_product_fact_prevents_exclusion(self):
        s,r=self.inputs();r['positive_facts'].append(dict(r['positive_facts'][0],kind='product_fact'))
        self.assertFalse(confirmed_outside(s,r,{1},T1))
    def test_environment_and_environment_opinion_both_outside_product_topic(self):
        # Actual T1 land-auction regression: external transport details plus
        # a judgement of railway convenience/noise are both non-product types.
        s,r=self.inputs()
        r['positive_facts'].append(dict(r['positive_facts'][0],kind='opinion',
            fact='临铁便利与噪音硬伤并存',why='外部环境评价，不是产品配置'))
        self.assertTrue(confirmed_outside(s,r,{1},T1))
        self.assertFalse(confirmed_outside(s,r,{1},T2))
    def test_mixed_outside_types_with_quality_fact_must_not_be_excluded(self):
        s,r=self.inputs()
        r['positive_facts'].append(dict(r['positive_facts'][0],kind='opinion'))
        r['positive_facts'].append(dict(r['positive_facts'][0],kind='quality_defect'))
        self.assertFalse(confirmed_outside(s,r,{1},T1))
    def test_missing_or_unknown_evidence_not_exclusion(self):
        s,r=self.inputs();self.assertFalse(confirmed_outside(s,r,{2},T1))
        r['positive_facts']=[];self.assertFalse(confirmed_outside(s,r,{1},T1))
    def test_disagreeing_type_not_exclusion(self):
        s,r=self.inputs();s['content_kind']='product_fact'
        self.assertFalse(confirmed_outside(s,r,{1},T1))
    def test_unknown_topic_and_malformed_inputs_not_exclusion(self):
        s,r=self.inputs();self.assertFalse(confirmed_outside(s,r,{1},'其他'))
        self.assertFalse(confirmed_outside(s,{'exclude':False,'positive_facts':[None]},{1},T1))


if __name__=='__main__':unittest.main()
