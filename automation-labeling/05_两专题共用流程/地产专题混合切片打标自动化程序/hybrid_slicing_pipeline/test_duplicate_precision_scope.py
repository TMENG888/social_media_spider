import unittest
from duplicate_precision_scope import issue


class PrecisionScopeTests(unittest.TestCase):
    def decision(self,why,**updates):
        return dict({'same_object':True,'same_fact':False,'why':why},**updates)
    def test_actual_precision_only_decisions_request_independent_review(self):
        for reason in ('A描述房间空鼓多达30处，是一个模糊的总数；B详细列出901、902各房间数量，两者事实细节不同。',
                       'A是过多空鼓的定性描述，B给出具体检测数量，事实精度不同。'):
            self.assertTrue(issue(self.decision(reason)))
    def test_distinct_defects_are_not_treated_as_precision_only(self):
        self.assertIsNone(issue(self.decision('A具体描述管道缺失，B详细记录空鼓总数，是完全不同缺陷。')))
    def test_different_objects_and_uncertainty_are_not_reclassified(self):
        self.assertIsNone(issue(self.decision('总数与详细数量不同',same_object=False)))
        self.assertIsNone(issue(self.decision('总数与详细数量不同',same_fact=None)))
    def test_same_fact_and_empty_reason_not_changed(self):
        self.assertIsNone(issue(self.decision('总数与详细数量',same_fact=True)))
        self.assertIsNone(issue(self.decision('')))


if __name__=='__main__':unittest.main()
