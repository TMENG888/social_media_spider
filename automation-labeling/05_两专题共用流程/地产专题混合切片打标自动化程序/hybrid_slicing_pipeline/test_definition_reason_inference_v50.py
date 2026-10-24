import unittest
from definition_reason_inference_v50 import assumption_reason


class DefinitionInference(unittest.TestCase):
    def test_definition_match_not_assumption(self):
        self.assertFalse(assumption_reason('原文明确地漏自动补水、水封大于50毫米，属于规格配置，故支持。'))
        self.assertFalse(assumption_reason('专用耐高温密封胶属于具体施工工艺，因此符合精装质量定义。'))

    def test_negation_preserved(self):
        for phrase in ('无需推断','并非推测','未根据行业常识推断','不能额外推断','不依赖行业惯例推测'):
            self.assertFalse(assumption_reason('原文明确说明两间家政间，'+phrase+'。'))

    def test_actual_assumption_still_flagged(self):
        for reason in ('南向四面宽通常包含主卧朝南','在房地产语境下对应高层住宅',
                       '根据行业常识，这里存在一套衣柜','推断厨房配置窗户','衣帽间隐含的衣柜配置'):
            self.assertTrue(assumption_reason(reason))

    def test_negation_does_not_mask_separate_affirmed_assumption(self):
        self.assertTrue(assumption_reason('数量无需推断，但通常包含主卧朝南。'))

    def test_quantity_inconsistency_alarms_remain(self):
        self.assertTrue(assumption_reason('明确存在1个，但非数量描述。'))
        self.assertTrue(assumption_reason('取主要数值作为面积。'))


if __name__=='__main__':unittest.main()
