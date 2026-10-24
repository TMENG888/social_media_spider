import unittest


class ObservedDefinitionReasonFalsePositives(unittest.TestCase):
    def test_matching_definition_is_not_industry_inference(self):
        reason='原文明示厨房烟道阀使用专用耐高温密封胶。这属于具体施工工艺，符合精装质量定义，故支持。'
        self.assertFalse(assumption_reason(reason))

    def test_configuration_or_specification_reason_is_not_inference(self):
        reason='原文地漏自动补水、共用存水弯，水封大于50毫米。这些属于规格和配置，故支持。'
        self.assertFalse(assumption_reason(reason))

    def test_negated_inference_does_not_veto_literal_evidence(self):
        self.assertFalse(assumption_reason('原文明示独立家政间数量为两间，无需推断。'))

    def test_actual_generalized_assumption_still_flagged(self):
        self.assertTrue(assumption_reason('住宅通常包含独立厨房，因此推断有厨房窗。'))
from semantic_inference_flags import assumption_reason, unsupported_scope

class InferenceFlags(unittest.TestCase):
    def test_large_flat_not_tall_building(self):
        tag={'l3':'大高'}
        self.assertIsNotNone(unsupported_scope(tag,'精装大平层','明确大高产品'))
        self.assertIsNone(unsupported_scope(tag,'40层高层住宅大平层','明示楼层'))
    def test_garden_or_interior_not_facade(self):
        tag={'l4':'外立面风格'}
        self.assertIsNotNone(unsupported_scope(tag,'园林采用现代中式风格','中式风格'))
        self.assertIsNone(unsupported_scope(tag,'建筑外立面采用现代中式风格','对象明示'))
        self.assertIsNotNone(unsupported_scope(tag,'中式细节拉满','风格明确'))
        self.assertIsNone(unsupported_scope(tag,'现代中式','风格明确','建筑外立面'))
        self.assertIsNotNone(unsupported_scope({'l4':'外立面性能'},'五重静界体系','已认证'))
    def test_third_party_target_customers_not_personal_concern(self):
        tag={'l1':'客户','l3':'购房关注点'}
        self.assertIsNotNone(unsupported_scope(tag,'客群跨度更大，从首改到终改都能覆盖','本人关注'))
        self.assertIsNotNone(unsupported_scope(tag,'适合二胎家庭长期居住','户型关注'))
        self.assertIsNone(unsupported_scope(tag,'我正在考虑这个适合二胎家庭的户型','自述关注'))
        self.assertIsNone(unsupported_scope(tag,'多少钱？','本人询问价格'))
    def test_four_connected_functions_not_four_bedroom_layout(self):
        tag={'l3':'通用','l4':'标准户型'}
        self.assertIsNotNone(unsupported_scope(tag,'四室贯通：客厅、餐厅、厨房、阳台打破传统隔阂',
                                              '明确四室户型'))
        self.assertIsNone(unsupported_scope(tag,'三房两厅两卫，客餐厨阳台四室贯通',
                                           '三房两厅两卫标准户型'))
    def test_unstated_room_orientation_is_review_trigger(self):
        self.assertTrue(assumption_reason('南向四面宽通常包含主卧朝南'))
    def test_direct_fact_not_flagged(self):
        self.assertFalse(assumption_reason('原文明确主卧朝南且宽度4米'))
    def test_bathroom_window_not_bedroom(self):
        self.assertIsNotNone(unsupported_scope({'l3':'主卧','l4':'窗'},'主卧配备转角窗主卫','原文明确窗配置'))
        self.assertIsNone(unsupported_scope({'l3':'主卧','l4':'窗'},'主卧设落地窗，主卫设转角窗','分别明确'))
    def test_room_width_not_whole_unit(self):
        self.assertIsNotNone(unsupported_scope({'l3':'通用','l4':'面宽'},'约9.2米宽厅','给出尺寸'))
        self.assertIsNone(unsupported_scope({'l3':'客厅','l4':'尺度'},'约9.2米宽厅','客厅尺寸'))
    def test_ldkb_not_horizontal_layout(self):
        self.assertIsNotNone(unsupported_scope({'l3':'通用','l4':'横厅/竖厅'},'LDKB一体化宽厅','明确'))
        self.assertIsNone(unsupported_scope({'l3':'通用','l4':'横厅/竖厅'},'LDKB一体化横厅','明确横厅'))
    def test_luxury_not_quality(self):
        self.assertIsNotNone(unsupported_scope({'l3':'精装质量'},'豪装交付','交付档次'))
        self.assertIsNone(unsupported_scope({'l3':'精装质量'},'精装交付墙面空鼓','明确缺陷'))
    def test_closet_room_not_installed_cabinet(self):
        self.assertIsNotNone(unsupported_scope({'l3':'主卧','l4':'衣柜'},'双步入衣帽间','明确空间'))
        self.assertIsNone(unsupported_scope({'l3':'主卧','l4':'衣柜'},'衣帽间设定制衣柜','配置明确'))
    def test_facility_question_not_location_concern(self):
        tag={'l1':'客户','l4':'地段位置'}
        self.assertIsNotNone(unsupported_scope(tag,'体育场规划你掌握吗','关注设施'))
        self.assertIsNone(unsupported_scope(tag,'体育场距离小区太远','位置关注'))
    def test_housekeeping_requires_explicit_count(self):
        tag={'l3':'家政间','l4':'数量'}
        self.assertIsNotNone(unsupported_scope(tag,'专属家政套房','存在家政空间'))
        self.assertIsNone(unsupported_scope(tag,'一个独立家政间','明确一个'))

if __name__=='__main__':unittest.main()
