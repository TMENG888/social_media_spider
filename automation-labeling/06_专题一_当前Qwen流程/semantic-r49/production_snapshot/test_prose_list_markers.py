import unittest
from prose_list_markers import without_list_markers

class ListMarkers(unittest.TestCase):
    def test_formatting_markers_not_measurements(self):
        self.assertEqual('地漏水封50毫米。\n厨房密封。',without_list_markers('1. 地漏水封50毫米。\n2. 厨房密封。'))
    def test_decimal_parameter_and_unspaced_number_retained(self):
        text='1.43为容积率；\n2.5米层高\n1个家政间'
        self.assertEqual(text,without_list_markers(text))

if __name__=='__main__':unittest.main()
