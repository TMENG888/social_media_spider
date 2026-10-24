import unittest
from prose_source_constraints import issues


class ChronologyTests(unittest.TestCase):
    source='目前称房屋质量合格。但之前接受其他媒体采访时称对空鼓等问题已经开始整改维修。'
    def test_omitted_temporal_qualifier_is_not_a_repair(self):
        self.assertTrue(issues(self.source,'对空鼓等问题开始整改维修。'))
        self.assertTrue(issues(self.source,'随后承认并开始整改维修。'))

    def test_previous_claim_retains_its_original_time(self):
        self.assertFalse(issues(self.source,'开发商当前称质量合格，此前曾称已对空鼓开始整改维修。'))

    def test_explicit_current_completion_or_unrelated_topic_is_not_rejected(self):
        self.assertFalse(issues(self.source+'目前已完成整改。','目前完成整改。'))
        self.assertFalse(issues('采访时介绍如何设置密封胶。','采用密封胶处理接口。'))


if __name__=='__main__':unittest.main()
