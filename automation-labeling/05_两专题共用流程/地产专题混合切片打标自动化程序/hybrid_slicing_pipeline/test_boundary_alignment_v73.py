import unittest
from unittest.mock import patch
import delivery_v73 as v


class AlignedBoundaryTests(unittest.TestCase):
    def test_review_issue_does_not_leave_new_plan_on_old_segment_positions(self):
        doc = {'text': '甲乙丙丁'}
        old = [{'start': 0, 'end': 2, 'text': '甲乙'}, {'start': 2, 'end': 4, 'text': '丙丁'}]
        plan = {'units': [{'source_start_id': 1, 'source_end_id': 1},
                          {'source_start_id': 2, 'source_end_id': 2}]}
        new = [{'start': 0, 'end': 4, 'text': '甲乙丙丁'}]
        out = {'units': [{'source_start_id': 1, 'source_end_id': 1}]}
        with patch.object(v.pipeline.final_boundary, 'review', return_value=(out, new, [], [], ['语义仍待核'])):
            result = v.final_scope_review(doc, plan, old, None)
        self.assertEqual(old, new)
        self.assertEqual(result[0], out)
        self.assertEqual(result[3], ['语义仍待核'])

    def test_invalid_return_never_discards_source_tail(self):
        doc = {'text': '甲乙丙丁'}
        old = [{'start': 0, 'end': 4, 'text': doc['text']}]
        plan = {'units': [{'source_start_id': 1, 'source_end_id': 1}]}
        bad = [{'start': 0, 'end': 2, 'text': '甲乙'}]
        with patch.object(v.pipeline.final_boundary, 'review', return_value=(plan, bad, [], [], [])):
            result = v.final_scope_review(doc, plan, old, None)
        self.assertEqual(old[0]['end'], 4)
        self.assertTrue(result[3])

    def test_wrong_numbered_plan_rejected_even_when_text_covers_source(self):
        ss = [{'start': 0, 'end': 4, 'text': '甲乙丙丁'}]
        self.assertFalse(v.aligned('甲乙丙丁', {'units': [{'source_start_id': 1, 'source_end_id': 2}]}, ss))


if __name__ == '__main__':
    unittest.main()
