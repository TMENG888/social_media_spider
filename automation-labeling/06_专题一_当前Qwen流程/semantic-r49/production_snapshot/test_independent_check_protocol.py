import unittest
from independent_check_protocol import select_checks, merge_repair
class Checks(unittest.TestCase):
    def test_missing_other_key_does_not_erase_valid_noise(self):
        good={'choice_key':'D0157','status':'supported','why':'有飞机噪音证据'}
        valid,missing=select_checks([good],{'D0157','D0001'})
        self.assertEqual([good],valid);self.assertEqual({'D0001'},missing)
    def test_duplicate_or_illegal_never_first_match(self):
        c={'choice_key':'D1','status':'supported','why':'有据'}
        valid,missing=select_checks([c,c,{'choice_key':'BAD','status':'supported','why':'非法'}],{'D1'})
        self.assertEqual([],valid);self.assertEqual({'D1'},missing)
    def test_malformed_status_not_support(self):
        valid,missing=select_checks([{'choice_key':'D1','status':'maybe','why':'待核'}],{'D1'})
        self.assertEqual([],valid);self.assertEqual({'D1'},missing)
    def test_repair_cannot_overwrite_valid_other_key(self):
        good={'choice_key':'D1','status':'supported','why':'逐字有据'}
        bad={'choice_key':'D1','status':'unsupported','why':'不应覆盖'}
        new={'choice_key':'D2','status':'unsupported','why':'确无相关事实'}
        valid,missing=merge_repair([good],[bad,new],{'D1','D2'})
        self.assertEqual([good,new],valid);self.assertEqual(set(),missing)
if __name__=='__main__':unittest.main()
