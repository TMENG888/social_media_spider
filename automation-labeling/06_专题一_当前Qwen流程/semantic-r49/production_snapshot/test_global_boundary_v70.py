import unittest
import full_source_boundary_v70 as v
import delivery_v11 as p


class GlobalBoundaryTests(unittest.TestCase):
    def unit(self, quote, n=1):
        return {'start_quote': quote, 'start_occurrence': n, 'object': '完整对象',
                'theme': '完整主题', 'why': '实际对象转换', 'confidence': .92, 'uncertainties': []}

    def test_long_anchor_crosses_sentence_directory_but_not_source(self):
        text = '甲对象。乙对象参数。乙对象解释。丙对象。'
        raw = {'units': [self.unit('甲对象。'), self.unit('乙对象参数。乙对象解释。'), self.unit('丙对象。')]}
        plan, segments, errors = v.materialize(text, raw, p.quote_partition)
        self.assertEqual(errors, [])
        self.assertEqual(''.join(s['text'] for s in segments), text)
        self.assertEqual(segments[1]['text'], '乙对象参数。乙对象解释。')

    def test_model_can_split_inside_sentence(self):
        text = '甲园林采用自然风格，乙会所设泳池和茶室。'
        raw = {'units': [self.unit('甲园林'), self.unit('乙会所')]}
        self.assertEqual(v.locate(text, raw), ([0, text.index('乙会所')], []))

    def test_ambiguous_occurrence_is_explicit(self):
        text = '对象甲对象乙对象丙'
        raw = {'units': [self.unit('对象', 1), self.unit('对象', 3)]}
        self.assertEqual(v.locate(text, raw), ([0, 6], []))

    def test_rewritten_quote_cannot_be_silently_normalized(self):
        self.assertTrue(v.locate('甲“对象”', {'units': [self.unit('甲"对象"')]})[1])

    def test_missing_opening_or_duplicate_start_rejected(self):
        self.assertTrue(v.locate('甲乙', {'units': [self.unit('乙')]})[1])
        self.assertTrue(v.locate('甲乙', {'units': [self.unit('甲'), self.unit('甲')]})[1])


if __name__ == '__main__':
    unittest.main()
