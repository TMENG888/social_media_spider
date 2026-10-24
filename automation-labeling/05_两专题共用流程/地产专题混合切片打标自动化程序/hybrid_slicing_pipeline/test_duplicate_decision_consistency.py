import unittest
from duplicate_decision_consistency import decision_issue


class ConsistencyTests(unittest.TestCase):
    def test_actual_different_fact_with_keep_side_contradiction(self):
        self.assertIsNotNone(decision_issue({'same_object': True, 'same_fact': False,
            'keep_side': 'B', 'why': 'A抽象，B具体，故保留B侧'}))

    def test_reason_only_contradiction(self):
        self.assertIsNotNone(decision_issue({'same_object': True, 'same_fact': False,
            'keep_side': None, 'why': '两者不同，故保留B侧'}))

    def test_uncertain_is_not_a_duplicate(self):
        self.assertIsNone(decision_issue({'same_object': True, 'same_fact': None,
            'keep_side': None, 'why': '未能确定对象配置关系，双方保留'}))

    def test_different_values_remain_distinct(self):
        self.assertIsNone(decision_issue({'same_object': True, 'same_fact': False,
            'keep_side': None, 'why': '95-108与95-105不同，不能归并'}))

    def test_different_projects_remain_distinct(self):
        self.assertIsNone(decision_issue({'same_object': False, 'same_fact': True,
            'keep_side': None, 'why': '两个项目同为三居，不归并'}))

    def test_supported_restatement(self):
        self.assertIsNone(decision_issue({'same_object': True, 'same_fact': True,
            'keep_side': 'B', 'why': '同一项目同一配置，B更具体，保留B侧'}))

    def test_same_fact_reason_cannot_reject_coalescing(self):
        self.assertIsNotNone(decision_issue({'same_object': True, 'same_fact': True,
            'keep_side': 'B', 'why': '两者不同事实，不能归并'}))


if __name__ == '__main__':
    unittest.main()
