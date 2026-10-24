import unittest
from additional_object_scope_evidence import scope_issue


class AdditionalScopeTests(unittest.TestCase):
    def test_external_ecological_corridor_not_community_landscape(self):
        tag={'l1':'产品','l2':'公区','l3':'景观','l4':'面积'}
        self.assertIsNotNone(scope_issue(tag,'约200亩绿野谷生态走廊，未来与滨河水岸构建生态住区','景观面积明确'))
        self.assertIsNone(scope_issue(tag,'项目内部自建生态走廊，占地2000平方米','明确内部景观'))
        self.assertIsNone(scope_issue(tag,'社区园林采用玉兰意象','设计风格明确'))
    def test_tour_title_is_not_personal_purchase_attention(self):
        tag={'l1':'客户','l4':'近期关注项目'}
        self.assertIsNotNone(scope_issue(tag,'春节探盘｜海淀实景豪宅某项目','自媒体发布探盘表示关注'))
        self.assertIsNone(scope_issue(tag,'我探盘后正在考虑这个项目','本人表达选择'))
    def test_unallocated_room_orientation(self):
        for room in ('客厅','主卧'):
            self.assertIsNotNone(scope_issue({'l3':room,'l4':'朝向'},'南向四面宽','原文明示'))

    def test_explicit_room_orientation(self):
        self.assertIsNone(scope_issue({'l3':'客厅','l4':'朝向'},'南向四面宽，其中客厅朝南','原文明示'))

    def test_house_not_submarket(self):
        self.assertIsNotNone(scope_issue({'l1':'土地','l2':'板块','l4':'板块档次'},'唯一低密豪宅','原文明示'))

    def test_explicit_submarket(self):
        self.assertIsNone(scope_issue({'l1':'土地','l2':'板块','l4':'板块档次'},'公开资料称该板块为豪宅板块','记录作者声称'))

    def test_house_not_land_condition(self):
        self.assertIsNotNone(scope_issue({'l1':'土地','l2':'地块','l4':'层高'},'层高3.1米','直接记录'))

    def test_explicit_design_condition(self):
        self.assertIsNone(scope_issue({'l1':'土地','l2':'地块','l4':'层高'},'设计图标明3号楼标准层层高3.15米','直接记录'))

    def test_same_height_valid_for_floorplan(self):
        self.assertIsNone(scope_issue({'l1':'产品','l2':'户型','l3':'通用','l4':'层高'},'层高3.1米','直接记录'))

    def test_unusual_wording_does_not_bypass_assumption_check(self):
        self.assertIsNotNone(scope_issue({'l3':'客厅','l4':'朝向'},'南向四面宽','通常四面宽指客厅及卧室朝南'))

    def test_community_services_not_necessarily_healthcare(self):
        self.assertIsNotNone(scope_issue({'l4':'社区卫生服务中心'},'旁边有社区服务机构','配套明确'))
        self.assertIsNone(scope_issue({'l4':'社区卫生服务中心'},'旁边有社区卫生服务中心','医疗配套明确'))

    def test_noise_result_not_automatically_facade_performance(self):
        self.assertIsNotNone(scope_issue({'l4':'外立面性能'},'外面听到飞机，家里听不到','隔音良好'))
        self.assertIsNone(scope_issue({'l4':'外立面性能'},'外窗夹胶玻璃用于隔音','明确构造'))

    def test_historical_home_not_current_profile(self):
        self.assertIsNotNone(scope_issue({'l4':'当前居住区域'},'之前就住机场旁边小区','居住区域明确'))
        self.assertIsNone(scope_issue({'l4':'当前居住区域'},'之前搬过家，现在住机场旁边','当前区域明确'))


if __name__=='__main__':unittest.main()
