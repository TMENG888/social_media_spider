import unittest
import delivery_v4 as v
from test_delivery_v4 import fixture, TAG, BUS

class NumericIntegration(unittest.TestCase):
    def test_chinese_distance_same_numeric_value(self):
        self.assertEqual(v.evidence_numeric_values('五公里范围内'),
                         v.evidence_numeric_values('5公里范围内'))
        self.assertEqual({'5'},v.evidence_numeric_values('五公里范围内'))
    def test_distance_new_number_remains_outside_source(self):
        self.assertEqual({'6'},v.evidence_numeric_values('6公里')-v.evidence_numeric_values('五公里'))
    def test_list_number_does_not_clear_supported_practice(self):
        doc,unit,review=fixture(topic=v.T1)
        unit['practice']='1. 住宅精装配置中央空调设备。'
        result,issues=v.validated_unit(doc,unit,0,doc['text'],[TAG],BUS,review)
        row=result[0]
        self.assertEqual(unit['practice'],row['具体产品做法'])
        self.assertFalse(any('原文外数字' in x for x in issues))
    def test_new_measurement_remains_blocked(self):
        doc,unit,review=fixture(topic=v.T1)
        unit['practice']='住宅精装配置中央空调，长度50米。'
        result,issues=v.validated_unit(doc,unit,0,doc['text'],[TAG],BUS,review)
        row=result[0]
        self.assertEqual('',row['具体产品做法'])
        self.assertTrue(any('原文外数字' in x for x in issues))

if __name__=='__main__':unittest.main()
