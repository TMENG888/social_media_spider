import unittest
import focused_object_boundary_v72 as v
import full_source_boundary_v70 as global_boundaries
import delivery_v11 as p


class FocusedObjectTests(unittest.TestCase):
    def piece(self, anchor, obj):
        return {'start_anchor': anchor, 'start_occurrence': 1, 'physical_object': obj,
                'why': '实际对象转换', 'confidence': .92, 'uncertainties': []}

    def test_internal_facility_transitions_preserve_every_character(self):
        text = '甲园林有绿植，甲会所有泳池。乙园林有步道，乙会所有茶室。'
        raw = {'pieces': [self.piece(None, '甲园林'), self.piece('甲会所', '甲会所'),
                          self.piece('乙园林', '乙园林'), self.piece('乙会所', '乙会所')]}
        proposal, errors = v.proposal(text, raw)
        self.assertEqual(errors, [])
        plan, ss, errors = global_boundaries.materialize(text, proposal, p.quote_partition)
        self.assertEqual(errors, [])
        self.assertEqual(''.join(s['text'] for s in ss), text)
        self.assertEqual(len(ss), 4)

    def test_model_must_retain_focus_opening_not_skip_it(self):
        self.assertTrue(v.proposal('甲对象', {'pieces': [self.piece('对象', '甲')]})[1])

    def test_single_object_is_not_forced_to_split(self):
        text = '厨房系统有风压、止逆阀和密封要求，参数解释仍是同一系统。'
        proposal, errors = v.proposal(text, {'pieces': [self.piece(None, '厨房系统')]})
        self.assertEqual(errors, [])
        self.assertEqual(len(global_boundaries.materialize(text, proposal, p.quote_partition)[1]), 1)

    def test_model_owned_adjacent_groups_cover_source_without_reordering(self):
        text = '卫生间提问。卫生间回答。厨房方案。'
        initial, _ = v.proposal(text, {'pieces': [self.piece(None, '卫生间'),
            self.piece('卫生间回答', '卫生间'), self.piece('厨房方案', '厨房')]})
        plan, ss, _ = global_boundaries.materialize(text, initial, p.quote_partition)
        groups = {'groups': [{'members': ['PART-1', 'PART-2'], 'physical_object': '卫生间',
                             'why': '提问与紧接回答', 'confidence': .95, 'uncertainties': []},
                            {'members': ['PART-3'], 'physical_object': '厨房',
                             'why': '对象转换', 'confidence': .94, 'uncertainties': []}]}
        proposal, errors = v.grouped_proposal(text, plan, ss, groups)
        self.assertEqual(errors, [])
        _, merged, errors = global_boundaries.materialize(text, proposal, p.quote_partition)
        self.assertEqual(errors, [])
        self.assertEqual(''.join(s['text'] for s in merged), text)
        self.assertEqual(merged[0]['text'], '卫生间提问。卫生间回答。')
        groups['groups'][0]['members'] = ['PART-1', 'PART-3']
        self.assertTrue(v.grouped_proposal(text, plan, ss, groups)[1])


if __name__ == '__main__':
    unittest.main()
