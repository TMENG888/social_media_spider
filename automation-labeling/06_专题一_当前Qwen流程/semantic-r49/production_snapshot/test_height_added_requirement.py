import unittest
from definition_rejection_guard import added_requirement_reason


class HeightRequirement(unittest.TestCase):
    definition={'emphasis':'户型层高','instruction':'记录套内户型整体的层高，保留对象、数值和单位。'}
    def test_net_height_not_in_dictionary_triggers_review_not_acceptance(self):
        self.assertTrue(added_requirement_reason('这是建筑结构层高，非套内净高，非特定户型。',self.definition))
    def test_actual_net_requirement_is_not_waived(self):
        self.assertFalse(added_requirement_reason('非套内净高',{'emphasis':'净高','instruction':'只记录套内净高'}))
    def test_wrong_public_object_is_not_automatically_a_dispute(self):
        self.assertFalse(added_requirement_reason('原文是会所层高，不是住宅套内对象。',self.definition))
    def test_other_dimensions_are_not_affected(self):
        self.assertFalse(added_requirement_reason('非特定户型',{'emphasis':'餐厅面积'}))


if __name__=='__main__':unittest.main()
