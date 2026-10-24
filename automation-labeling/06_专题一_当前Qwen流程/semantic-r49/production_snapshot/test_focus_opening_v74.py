import unittest
import delivery_v74 as v
import full_source_boundary_v70 as b
import delivery_v11 as p


class LiteralOpeningTests(unittest.TestCase):
    def piece(self, anchor):
        return {'start_anchor': anchor, 'start_occurrence': 1, 'physical_object': '实际对象',
                'why': '完整对象', 'confidence': .92, 'uncertainties': []}

    def test_literal_opening_equals_null_opening(self):
        text = '甲对象完整介绍。'
        for anchor in [None, text]:
            raw, errors = v.proposal(text, {'pieces': [self.piece(anchor)]})
            self.assertEqual(errors, [])
            self.assertEqual(b.materialize(text, raw, p.quote_partition)[1][0]['text'], text)

    def test_literal_anchor_cannot_skip_intro(self):
        text = '甲对象完整介绍。'
        raw, _ = v.proposal(text, {'pieces': [self.piece('对象完整介绍。')]})
        self.assertTrue(b.materialize(text, raw, p.quote_partition)[2])


if __name__ == '__main__':
    unittest.main()
