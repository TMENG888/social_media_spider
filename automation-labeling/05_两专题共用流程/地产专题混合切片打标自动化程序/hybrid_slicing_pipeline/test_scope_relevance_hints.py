import unittest
from scope_relevance_hints import exclusion_review_hint

class RelevanceHints(unittest.TestCase):
    def test_waiting_and_planning_questions_not_silently_lost(self):
        for text in ['挑花眼了感觉这个也不错，继续做等等党','最近看到体育场的规划，掌握吗']:
            self.assertIsNotNone(exclusion_review_hint('北京臻澐项目口碑',text))
    def test_pure_group_promotion_does_not_become_fact(self):
        self.assertIsNone(exclusion_review_hint('北京臻澐项目口碑','汤师爷买房交流群'))
    def test_username_is_not_fact(self):
        self.assertIsNone(exclusion_review_hint('北京臻澐项目口碑','【父评论｜5层洋房】交流群'))
    def test_mixed_invitation_fact_can_be_reviewed_without_auto_tag(self):
        self.assertIsNotNone(exclusion_review_hint('北京臻澐项目口碑','关注海淀5层洋房，留言领取资料'))

if __name__=='__main__':unittest.main()
