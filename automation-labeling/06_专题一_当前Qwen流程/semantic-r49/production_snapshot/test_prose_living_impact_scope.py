import unittest
from prose_living_impact_scope import issues


class LivingImpact(unittest.TestCase):
    def test_explicit_qualifier_omission_is_flagged(self):
        self.assertTrue(issues('开窗能听见但不至于影响生活，户外有点害怕。','开窗及户外能听见，令人害怕。'))
    def test_literal_or_paraphrased_limitation_is_allowed(self):
        for text in ('开窗可闻但不影响生活，户外声大。','开窗可闻，生活影响不大。'):
            self.assertFalse(issues('不至于影响生活',text))
    def test_no_limitation_is_not_invented(self):
        self.assertFalse(issues('小区飞机声大令人害怕','飞机声大令人害怕'))
    def test_other_kind_of_nonimpact_does_not_trigger(self):
        self.assertFalse(issues('不影响容积率','调整布局'))
    def test_empty_summary_stays_under_existing_missing_prose_checks(self):
        self.assertFalse(issues('不影响生活',None))


if __name__=='__main__':unittest.main()
