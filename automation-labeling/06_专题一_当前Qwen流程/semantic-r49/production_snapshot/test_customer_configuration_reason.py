import unittest
from customer_configuration_reason import issue


class CustomerConfigurationTests(unittest.TestCase):
    tag={'l1':'客户','l3':'购房关注点','l4':'精装'}
    def test_actual_advertisement_definition_confusion_is_flagged(self):
        for quote,reason in [('精装交付','原文直接陈述精装交付，符合精装标签定义'),
                             ('4室2厅3卫...三套房设计','原文明示格局，符合户型关注点定义'),
                             ('四居洋房...低密洋房','原文提及洋房，符合物业形态标签定义')]:
            self.assertTrue(issue(self.tag,quote,reason))
    def test_personal_judgement_without_i_is_not_vetoed(self):
        for quote in ('精装够用吗？','这个户型太大了','更喜欢低密洋房','想买四居洋房'):
            self.assertIsNone(issue(self.tag,quote,'评论者表达关注'))
    def test_product_and_other_customer_branches_are_not_restricted(self):
        self.assertIsNone(issue({'l1':'产品','l3':'装修标准'},'精装交付','配置描述'))
        self.assertIsNone(issue({'l1':'客户','l3':'个人信息'},'精装交付','配置描述'))
    def test_empty_or_unrecognised_quote_is_not_automatic_rejection(self):
        self.assertIsNone(issue(self.tag,'','需要其他证据核验'))


if __name__=='__main__':unittest.main()
