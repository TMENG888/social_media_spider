import unittest
from audit_numeric_quote_boundaries_v1113 import numeric_boundary_hits


class NumericQuoteBoundaryTests(unittest.TestCase):
    def test_truncated_decimal_is_not_clean_literal_evidence(self):
        self.assertTrue(numeric_boundary_hits('容积率仅1.433-5层纯洋房', '容积率仅1.43'))

    def test_tail_digit_cannot_be_silently_used_as_next_range(self):
        self.assertTrue(numeric_boundary_hits('容积率仅1.433-5层纯洋房', '3-5层纯洋房'))

    def test_whole_raw_token_remains_traceable(self):
        self.assertFalse(numeric_boundary_hits('容积率仅1.433-5层纯洋房', '容积率仅1.433-5层纯洋房'))

    def test_explicit_separator_and_whitespace(self):
        self.assertFalse(numeric_boundary_hits('容积率仅1.43，3-5层纯洋房', '容积率仅1.43'))
        self.assertFalse(numeric_boundary_hits('容积率仅 1.43，3-5层纯洋房', '3-5层纯洋房'))

    def test_regular_measurement(self):
        self.assertFalse(numeric_boundary_hits('会所设25米恒温泳池', '25米恒温泳池'))

    def test_empty_and_absent_quotes(self):
        self.assertFalse(numeric_boundary_hits('25米', ''))
        self.assertFalse(numeric_boundary_hits('25米', '26米'))


if __name__ == '__main__':
    unittest.main()
