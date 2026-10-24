import unittest
import definition_alternative_conditions as v

class ExampleScopeReview(unittest.TestCase):
    def setUp(self):self.tag={'instruction':'记录住宅通用设备的科技系统配置。例：温控系统。'}
    def test_industry_typical_exclusion_routes_to_review(self):
        self.assertTrue(v.review_reasons('设备通常不归类为这一系统，故不能标。',self.tag))
    def test_example_cannot_be_turned_into_closed_scope(self):
        self.assertTrue(v.review_reasons('定义示例为温控系统，且原文未提及温控，故不支持。',self.tag))
    def test_legitimate_no_object_not_routed(self):
        self.assertFalse(v.review_reasons('原文未提及任何设备、控制系统或配置。',self.tag))
    def test_no_example_no_example_scope_alarm(self):
        self.assertFalse(v.review_reasons('定义示例为某系统，原文未提及。',{'instruction':'必须明示规定系统。'}))

if __name__=='__main__':unittest.main()
