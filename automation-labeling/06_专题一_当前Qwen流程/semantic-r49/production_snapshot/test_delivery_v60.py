import unittest
from unittest.mock import patch
import delivery_v60 as v


class VisibleIntegrationTests(unittest.TestCase):
    def test_all_four_scope_requests_reach_cost_accounting(self):
        calls = [{'phase': str(i), 'status': 'success'} for i in range(4)]
        returned = (False, {}, {'_scope_call_metrics': calls}, dict(calls[0]))
        with patch.object(v, '_check_exclusion', return_value=returned):
            excluded, unit, audit, metric = v.check_exclusion({}, {}, [], object())
        self.assertEqual(metric['recovery_call'], calls[1])
        self.assertEqual(metric['countercheck_call'], calls[2])
        self.assertEqual(metric['countercheck_recovery_call'], calls[3])

    def test_failed_local_protocol_not_saved_as_complete(self):
        result = {'complete': True, 'local_acceptance': [{'case_id': 'unit-A',
                   'processing_contract_complete': False}], 'audit': []}
        with patch.object(v, '_process_document', return_value=result):
            actual = v.process_document()
        self.assertFalse(actual['complete'])

    def test_negative_scope_requires_independent_agreement(self):
        decision = {'exclude': True, 'needs_review': False, 'issues': [], 'kind': 'unrelated'}
        reply = {'allow_exclusion': False, 'source_keys': [], 'why': '真实观望态度应该保留', 'confidence': .95}
        with patch.object(v, '_scope_review', return_value=(decision, [], [])), \
             patch.object(v.visible, 'review', return_value=(reply, [], [], [])):
            actual, calls, audit = v.scope_review('还在比较，先等一等。', '住宅讨论', {}, object())
        self.assertFalse(actual['exclude'])
        self.assertTrue(actual['needs_review'])

    def test_failed_exclusion_countercheck_does_not_drop_comment(self):
        decision = {'exclude': True, 'needs_review': False, 'issues': [], 'kind': 'unrelated'}
        with patch.object(v, '_scope_review', return_value=(decision, [], [])), \
             patch.object(v.visible, 'review', return_value=(None, [], [], ['API未成功'])):
            actual, calls, audit = v.scope_review('还在比较。', '住宅讨论', {}, object())
        self.assertFalse(actual['exclude'])


if __name__ == '__main__':
    unittest.main()
