import unittest
from definition_rejection_guard import added_requirement_reason

class DefinitionRejection(unittest.TestCase):
    def test_specific_for_sale_unit_requirement_is_review_trigger_only(self):
        self.assertTrue(added_requirement_reason('无法确证这是特定待售房源的配套数据，板块不等于具体项目'))
    def test_redundancy_and_measurement_extra_condition_reviewed(self):
        self.assertTrue(added_requirement_reason('飞机噪音应由机场标签覆盖，未提供噪音数值监测数据'))
    def test_object_absence_is_not_auto_rescued(self):
        self.assertFalse(added_requirement_reason('原文没有餐厅或尺寸信息'))
    def test_subjective_experience_rejection_requires_definition_review(self):
        self.assertTrue(added_requirement_reason('经过四个红绿灯仅为主观体验描述'))
    def test_attention_not_purchase_intent(self):
        self.assertTrue(added_requirement_reason('未表达本人关注价格作为决策因素，也未体现购买意向'))
    def test_question_not_blanket_unsupported(self):
        self.assertTrue(added_requirement_reason('仅为询问，未表达明确关注，非肯定性表述'))
        self.assertTrue(added_requirement_reason('未有最终决定，不能记录观望'))

if __name__=='__main__':unittest.main()
