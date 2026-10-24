import unittest
from unittest.mock import patch
import delivery_v64 as v


class FullCoverageTests(unittest.TestCase):
    def test_independent_additions_are_proposals_not_filtered_to_first_pass(self):
        with patch.object(v,'_selection',return_value=([{'choice_key':'D1'}],[],[],[])), \
             patch.object(v.coverage,'review',return_value=([{'choice_key':'D2'}],[],[],[])) as extra:
            rows, calls, audit, errors=v.selection_review('真实原文',{'D1':{},'D2':{}},'',{},None)
        self.assertEqual({x['choice_key'] for x in rows},{'D1','D2'})
        self.assertEqual(set(extra.call_args.args[1]),{'D1','D2'})

    def test_same_id_not_duplicated_by_second_pass(self):
        with patch.object(v,'_selection',return_value=([{'choice_key':'D1'}],[],[],[])), \
             patch.object(v.coverage,'review',return_value=([{'choice_key':'D1'}],[],[],[])):
            rows, calls, audit, errors=v.selection_review('真实原文',{'D1':{}},'',{},None)
        self.assertEqual(len(rows),1)

    def test_coverage_failure_is_not_silently_zero_omissions(self):
        with patch.object(v,'_selection',return_value=([],[],[],[])), \
             patch.object(v.coverage,'review',return_value=([],[],[],['独立核验API未成功'])):
            rows,calls,audit,errors=v.selection_review('原文',{'D1':{}},'',{},None)
        self.assertTrue(errors)


if __name__=='__main__':unittest.main()
