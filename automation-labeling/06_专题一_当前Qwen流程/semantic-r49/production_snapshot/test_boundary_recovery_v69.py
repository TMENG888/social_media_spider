import unittest
from unittest.mock import patch
import delivery_v69 as v


class InvalidProposalRecoveryTests(unittest.TestCase):
    def test_structurally_invalid_draft_only_enters_independent_review(self):
        draft = {'units': [{'start_phrase': '超过协议长度的原始模型短语'}]}
        final = {'units': [{'start_phrase': None}]}
        with patch.object(v.current.current, 'boundary_call', side_effect=[
            (None, [{'status': 'success'}], [{'raw_response': draft}], ['长度错误']),
            (final, [{'status': 'success'}], [{'raw_response': final}], [])]) as call:
            result = v.boundary_call('', {'source_text': '全文'}, {}, {}, '', None)
        self.assertEqual(result[0], final)
        self.assertEqual(result[3], [])
        self.assertEqual(call.call_args.args[1]['proposed_boundaries'], draft)
        self.assertEqual(call.call_args.args[1]['proposal_protocol_issues'], ['长度错误'])
        self.assertNotEqual(result[0], draft)

    def test_failed_api_does_not_trigger_recovery_on_incidental_raw_json(self):
        with patch.object(v.current.current, 'boundary_call', return_value=(
            None, [{'status': 'failed'}], [{'raw_response': {'units': []}}], ['API未成功'])) as call:
            result = v.boundary_call('', {}, {}, {}, '', None)
        self.assertEqual(result[3], ['API未成功'])
        self.assertEqual(call.call_count, 1)


if __name__ == '__main__':
    unittest.main()
