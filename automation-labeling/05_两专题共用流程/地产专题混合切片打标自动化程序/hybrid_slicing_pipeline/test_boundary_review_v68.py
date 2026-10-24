import unittest
from unittest.mock import patch
import delivery_v68 as v


class IndependentBoundaryReviewTests(unittest.TestCase):
    def test_fulltext_review_replaces_draft_not_program_boundary_rules(self):
        proposal = {'units': [{'object': '参数'}, {'object': '参数解释'}]}
        final = {'units': [{'object': '完整对象'}]}
        payload = {'source_text': '全文证据', 'source_catalog': [], 'all_applicable_labels': []}
        with patch.object(v.current, 'boundary_call', side_effect=[
            (proposal, ['first'], ['draft-audit'], []),
            (final, ['second'], ['review-audit'], [])]) as call:
            raw, calls, audit, errors = v.boundary_call('原协议', payload, {}, {}, 'draft', None)
        self.assertEqual(raw, final)
        self.assertEqual(calls, ['first', 'second'])
        self.assertEqual(audit, ['draft-audit', 'review-audit'])
        self.assertEqual(errors, [])
        self.assertEqual(call.call_args.args[1]['source_text'], payload['source_text'])
        self.assertEqual(call.call_args.args[1]['proposed_boundaries'], proposal)
        self.assertNotIn('proposed_boundaries', payload)

    def test_missing_response_does_not_synthesize_boundaries(self):
        with patch.object(v.current, 'boundary_call', return_value=(None, [], [], ['失败'])) as call:
            self.assertEqual(v.boundary_call('', {}, {}, {}, '', None)[3], ['失败'])
        self.assertEqual(call.call_count, 1)


if __name__ == '__main__':
    unittest.main()
