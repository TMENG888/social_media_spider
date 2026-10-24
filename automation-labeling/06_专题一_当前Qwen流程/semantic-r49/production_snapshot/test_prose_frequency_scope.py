import unittest
from prose_frequency_scope import issues


class FrequencyScope(unittest.TestCase):
    def test_different_event_denominator_not_borrowed(self):
        self.assertTrue(issues('常态起落10来次，非常态不一定。驱鸟一天也许有2次。','飞机常态起落10次/天。'))
    def test_explicit_daily_count_preserved(self):
        self.assertFalse(issues('每天常态起落10来次。','每天起落10次。'))
        self.assertFalse(issues('起落10次/天。','起落10次/天。'))
    def test_no_new_denominator_no_issue(self):
        self.assertFalse(issues('常态起落10来次。','常态起落10来次。'))
    def test_not_substring_of_other_number(self):
        self.assertFalse(issues('每天起落110次。','起落10次/天。'))
    def test_chinese_numeral_conversion_is_not_adjudicated_here(self):
        self.assertFalse(issues('每天起落十次。','起落10次/天。'))


if __name__=='__main__':unittest.main()
