"""Observed semantic regressions; source-neutral evidence/object cases.

Initially red on v11.13. These tests are not a global precision/recall score.
"""
import unittest
from semantic_inference_flags import unsupported_scope


class ScopeRegressionTests(unittest.TestCase):
    def test_four_bays_cannot_allocate_living_room_direction(self):
        self.assertIsNotNone(unsupported_scope({'l3':'客厅','l4':'朝向'},
            '南向四面宽','通常四面宽指客厅及卧室朝南，故客厅朝南'))

    def test_four_bays_cannot_allocate_bedroom_direction(self):
        self.assertIsNotNone(unsupported_scope({'l3':'主卧','l4':'朝向'},
            '南向四面宽','原文未列房间，但可由四面宽确定主卧朝向'))

    def test_explicit_living_room_direction_stays_valid(self):
        self.assertIsNone(unsupported_scope({'l3':'客厅','l4':'朝向'},
            '客厅朝南','直接记录客厅朝向，不新增配置'))

    def test_luxury_property_not_entire_submarket_grade(self):
        self.assertIsNotNone(unsupported_scope({'l1':'土地','l2':'板块','l3':'基础信息','l4':'板块档次'},
            '海淀四环内20年来唯一低密豪宅','项目/板块档次由豪宅表述明确'))

    def test_explicit_submarket_grade_stays_valid(self):
        self.assertIsNone(unsupported_scope({'l1':'土地','l2':'板块','l3':'基础信息','l4':'板块档次'},
            '资料将该板块定位为豪宅板块','记录公开板块档次，保留来源'))

    def test_house_height_not_land_planning_condition(self):
        self.assertIsNotNone(unsupported_scope({'l1':'土地','l2':'地块','l3':'土地基本指标','l4':'层高'},
            '层高3米1～3.3','原文明确房屋层高'))

    def test_explicit_design_scope_stays_valid(self):
        self.assertIsNone(unsupported_scope({'l1':'土地','l2':'地块','l3':'土地基本指标','l4':'层高'},
            '该地块规划条件规定住宅标准层层高3.15米','明确规划条件及适用对象'))


if __name__=='__main__':unittest.main()
