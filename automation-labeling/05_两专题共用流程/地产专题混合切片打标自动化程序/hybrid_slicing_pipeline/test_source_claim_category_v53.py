import unittest
import source_claim_category_v53 as v

class SourceClaimCategory(unittest.TestCase):
    def setUp(self):
        self.customer={'l1':'客户','l3':'购房关注点'}
        self.sales={'l1':'服务','l2':'销售服务'}
    def test_definition_in_reason_is_not_personal_evidence(self):
        self.assertTrue(v.issue(self.customer,'楼盘配了全屋智能系统，贴合互联网客群。','定义要求本人关注，故支持客户关注。'))
    def test_no_literal_I_required(self):
        for q in ('精装够用吗','更喜欢这个户型','这个装标太贵了'):
            self.assertIsNone(v.issue(self.customer,q))
    def test_actual_first_person_choice_supported(self):
        self.assertIsNone(v.issue(self.customer,'我们考虑这套精装房，最看重隔音。'))
    def test_product_configuration_not_sales_promise(self):
        self.assertTrue(v.issue(self.sales,'厨电卫浴是一线品牌，配了智能系统。','这些是销售承诺。'))
    def test_explicit_promise_experience_is_not_flagged(self):
        self.assertIsNone(v.issue(self.sales,'销售告诉我装标是这个品牌，合同附件写了。'))
    def test_product_tag_not_affected(self):
        self.assertIsNone(v.issue({'l1':'产品','l3':'通用设备'},'配了智能系统。'))
    def test_objective_public_space_impression_not_personal_choice(self):
        self.assertTrue(v.issue(self.customer,'大堂、公区视觉冲击很强，豪宅氛围鲜明。','定义要求本人关注，所以支持。'))
    def test_generic_appliance_not_specific_component(self):
        tag={'l1':'产品','l3':'厨房','l4':'油烟机+燃气灶'}
        self.assertTrue(v.issue(tag,'厨电都是一线品牌。'))
        self.assertIsNone(v.issue(tag,'配置高风压抽油烟机。'))
        self.assertIsNone(v.issue(tag,'燃气灶为指定品牌。'))

if __name__=='__main__':unittest.main()
