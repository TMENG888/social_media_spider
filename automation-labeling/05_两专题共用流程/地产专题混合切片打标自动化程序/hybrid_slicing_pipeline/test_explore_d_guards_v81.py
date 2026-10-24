import unittest
from explore_d_guards_v81 import hard_check
class TestGuard(unittest.TestCase):
 def test_actual_row_house(self):self.assertTrue(hard_check({'tag_id':'VOC-0168'},'英伦官邸排屋')[0])
 def test_marketing(self):self.assertFalse(hard_check({'tag_id':'VOC-0168'},'255平墅')[0])
 def test_numeric_area(self):
  for t in ['255平','255平墅产品','169㎡','217平米','230平方米']:self.assertTrue(hard_check({'tag_id':'VOC-0186'},t)[0])
 def test_no_unit(self):self.assertFalse(hard_check({'tag_id':'VOC-0186'},'230户型')[0])
 def test_width(self):
  self.assertFalse(hard_check({'tag_id':'VOC-0184'},'四面宽')[0]);self.assertTrue(hard_check({'tag_id':'VOC-0184'},'面宽17米')[0])
  self.assertFalse(hard_check({'tag_id':'VOC-0184'},'四面宽，极致层高3.5米')[0])
 def test_precise_price(self):
  self.assertFalse(hard_check({'tag_id':'VOC-0483'},'218.24㎡四居1826万')[0]);self.assertTrue(hard_check({'tag_id':'VOC-0483'},'豪装五居总价')[0])
if __name__=='__main__':unittest.main()
