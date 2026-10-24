import unittest
from unittest.mock import patch
import global_anchor_resolution_v71 as v
import bounded_visible_contract_v60 as visible
import delivery_v11 as p


class PositionConfirmationTests(unittest.TestCase):
    def unit(self, quote):
        return {'start_quote': quote, 'start_occurrence': 1, 'object': '实际对象',
                'theme': '完整主题', 'why': '实际转换', 'confidence': .92, 'uncertainties': []}

    def test_nbsp_candidate_preserves_literal_source_not_model_quote(self):
        text = '甲\u00a0对象完整介绍。'
        options = v.candidates(text, '甲 对象完整介绍。')
        self.assertEqual(options[0]['start'], 0)
        self.assertEqual(options[0]['literal_start'], text)

    def test_no_model_confirmation_no_programmatic_repair(self):
        raw = {'positions': [{'unit_index': 0, 'candidate_key': 'POS-0',
                              'confirmed': False, 'why': '无法确认', 'confidence': .5}]}
        with patch.object(visible, 'review', return_value=(raw, [], [], [])):
            result = v.review('甲对象', {'units': [self.unit('甲 对象')]}, {}, None, p.quote_partition)
        self.assertIsNone(result[0])
        self.assertTrue(result[4])

    def test_confirmed_source_position_is_lossless_and_confidence_not_raised(self):
        text = '甲\u00a0对象。乙对象。'
        raw = {'positions': [{'unit_index': 0, 'candidate_key': 'POS-0', 'confirmed': True,
                              'why': '相同原位置', 'confidence': .91},
                             {'unit_index': 1, 'candidate_key': 'POS-5', 'confirmed': True,
                              'why': '实际对象转换', 'confidence': .95}]}
        with patch.object(visible, 'review', return_value=(raw, [], [], [])):
            plan, ss, _, _, errors = v.review(text, {'units': [self.unit('甲 对象。'), self.unit('乙对象。')]},
                                             {}, None, p.quote_partition)
        self.assertEqual(errors, [])
        self.assertEqual(''.join(s['text'] for s in ss), text)
        self.assertEqual(plan['units'][0]['confidence']['boundary'], .91)


if __name__ == '__main__':
    unittest.main()
