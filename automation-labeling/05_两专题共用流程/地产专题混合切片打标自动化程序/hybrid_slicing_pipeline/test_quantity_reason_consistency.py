import unittest
from quantity_reason_consistency import issue


class QuantityConsistencyTests(unittest.TestCase):
    def test_actual_double_walk_in_not_silently_one(self):
        self.assertIsNotNone(issue({'l3': '衣帽间', 'l4': '数量'},
            '主卧配备双步入衣帽间', '记录存在1个衣帽间（双步入为入口形式，非数量2）'))

    def test_explicit_one_housekeeping_room_allowed(self):
        self.assertIsNone(issue({'l3': '家政间', 'l4': '数量'},
            '有一个独立家政间', '原文明示一个家政间，数量1'))

    def test_explicit_two_cloakrooms_allowed(self):
        self.assertIsNone(issue({'l3': '衣帽间', 'l4': '数量'},
            '男女各一间，共两个衣帽间', '明确计数两个'))

    def test_type_attribute_is_not_count(self):
        self.assertIsNone(issue({'l3': '玄关', 'l4': '类型'},
            '双入口玄关', '双入口为入口形式'))


if __name__ == '__main__':unittest.main()
