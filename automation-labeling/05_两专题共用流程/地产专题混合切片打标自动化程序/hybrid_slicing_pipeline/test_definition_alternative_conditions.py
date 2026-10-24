import unittest
import definition_alternative_conditions as policy


class AlternativeConditions(unittest.TestCase):
    def setUp(self):
        self.tag={'instruction':'记录住宅精装中卫生间的地漏配置；宣传或样板展示不等于实际交付。例：如交付清单列出品牌、型号、规格或配置。'}

    def test_observed_missing_brand_reason_is_review_lead(self):
        self.assertTrue(policy.review_reasons('仅描述自动补水及共用存水弯，未提及品牌、型号，不满足标签要求。',self.tag))

    def test_real_mandatory_brand_is_not_relaxed(self):
        tag={'instruction':'必须提供设备品牌。例：列出品牌、型号、规格或配置。'}
        self.assertFalse(policy.review_reasons('未提供品牌，不能支持。',tag))

    def test_absent_object_is_not_optional_condition_alarm(self):
        self.assertFalse(policy.review_reasons('原文未提及卫生间或地漏对象。',self.tag))

    def test_unsupported_workmanship_real_implementation_added_requirement(self):
        tag={'instruction':'记录明确的精装质量做法、检测或质量表现。例：具体施工做法。'}
        self.assertTrue(policy.review_reasons('虽回答专用胶密封接口，但未明确本项目实际采用该施工工艺。',tag))

    def test_actual_delivery_required_is_preserved(self):
        tag={'instruction':'仅记录实际交付的施工做法。例：已经施工的做法。'}
        self.assertFalse(policy.review_reasons('未证明本项目实际施工，无法支持。',tag))

    def test_material_without_workmanship_is_not_condition_alarm(self):
        tag={'instruction':'记录明确的精装质量做法、检测或质量表现。'}
        self.assertFalse(policy.review_reasons('只列材料名称，没有施工方式或质量表现。',tag))

    def test_detection_does_not_return_supported_tag_or_rewrite_dictionary(self):
        before=dict(self.tag)
        result=policy.review_reasons('原文明确描述自动补水配置，但未提供品牌型号，无法支持。',self.tag)
        self.assertEqual(before,self.tag);self.assertTrue(result);self.assertTrue(all(isinstance(r,str) for r in result))

    def test_absent_equipment_and_all_configuration_not_false_alarm(self):
        tag={'instruction':'记录中央空调配置。例：品牌、型号、规格或配置。'}
        self.assertFalse(policy.review_reasons('原文未提及中央空调的品牌、型号、规格或配置。',tag))


if __name__=='__main__':unittest.main()
