import unittest
from unittest.mock import patch
import catalogued_boundary_v65 as boundaries
import delivery_v67 as v


class ShortBoundaryTests(unittest.TestCase):
    def test_contract_limits_anchor_without_changing_source_or_schema(self):
        entries = [{'source_key': 'S1', 'start': 0, 'text': '甲园林。甲会所。'}]
        schema = boundaries.schema(entries)
        payload = {'source_text': entries[0]['text'], 'source_catalog': entries}
        with patch.object(v.current, 'boundary_call', return_value=(None, [], [], [])) as call:
            v.boundary_call('全文', payload, schema, {}, 'v11.65', None)
        actual = call.call_args.args
        self.assertIs(actual[1], payload)
        self.assertEqual(actual[2]['properties']['units']['items']['properties']['start_phrase']['maxLength'], 24)
        self.assertNotIn('maxLength', schema['properties']['units']['items']['properties']['start_phrase'])
        self.assertIn('编辑标题', actual[0])

    def test_internal_object_transition_is_literal_not_sentence_boundary(self):
        text = '甲园林采用自然风格，甲会所设泳池。'
        entries = [{'source_key': 'S1', 'start': 0, 'text': text}]
        raw = {'units': [{'start_source_key': 'S1', 'start_phrase': None, 'start_occurrence': 1},
                         {'start_source_key': 'S1', 'start_phrase': '甲会所', 'start_occurrence': 1}]}
        starts, errors = boundaries.positions(text, entries, raw)
        self.assertEqual(errors, [])
        self.assertEqual(starts, [0, text.index('甲会所')])

    def test_cross_entry_phrase_is_rejected_not_truncated(self):
        text = '甲园林。甲会所。'
        entries = [{'source_key': 'S1', 'start': 0, 'text': '甲园林。'},
                   {'source_key': 'S2', 'start': 4, 'text': '甲会所。'}]
        raw = {'units': [{'start_source_key': 'S1', 'start_phrase': '甲园林。甲会所', 'start_occurrence': 1}]}
        starts, errors = boundaries.positions(text, entries, raw)
        self.assertEqual(starts, [])
        self.assertTrue(errors)


if __name__ == '__main__':
    unittest.main()
