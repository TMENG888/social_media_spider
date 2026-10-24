import unittest
from article_identity_context import apply


class IdentityTests(unittest.TestCase):
    def fixture(self):
        source = '甲项目。小区距地铁750米。乙项目。'
        segments = [{'end': 4}, {'end': 14}, {'end': len(source)}]
        units = [{'source_end_id': 1}, {'source_end_id': 2}, {'source_end_id': 3}]
        entries = [{'unit_index': i, 'assigned': False} for i in range(3)]
        return source, units, segments, entries

    def test_grounded_antecedent_only_supplies_identity(self):
        source, units, segments, entries = self.fixture()
        entries[1] = {'unit_index': 1, 'assigned': True, 'identity_quote': '甲项目',
            'identity_occurrence': 1, 'why': '小区承接前文甲项目', 'confidence': .95}
        result, issues = apply(source, units, segments, {'contexts': entries})
        self.assertFalse(issues)
        self.assertEqual('甲项目', result[1]['object_quote'])
        self.assertNotIn('project_ids', result[1])
        self.assertNotIn('labels', result[1])
        self.assertNotIn('object_quote', units[1])

    def test_future_project_not_borrowed(self):
        source, units, segments, entries = self.fixture()
        entries[0] = {'unit_index': 0, 'assigned': True, 'identity_quote': '乙项目',
            'identity_occurrence': 1, 'why': '后文有该项目', 'confidence': .99}
        result, issues = apply(source, units, segments, {'contexts': entries})
        self.assertTrue(issues)
        self.assertNotIn('object_quote', result[0])

    def test_wrong_quote_or_occurrence_cannot_pass(self):
        for quote, occurrence in [('不存在', 1), ('甲项目', 2)]:
            source, units, segments, entries = self.fixture()
            entries[1] = {'unit_index': 1, 'assigned': True, 'identity_quote': quote,
                'identity_occurrence': occurrence, 'why': '承接', 'confidence': .99}
            result, issues = apply(source, units, segments, {'contexts': entries})
            self.assertTrue(issues)
            self.assertNotIn('object_quote', result[1])

    def test_duplicate_slot_fails_closed(self):
        source, units, segments, entries = self.fixture()
        entries[1]['unit_index'] = 0
        result, issues = apply(source, units, segments, {'contexts': entries})
        self.assertEqual(units, result)
        self.assertTrue(issues)

    def test_low_confidence_no_inherited_identity(self):
        source, units, segments, entries = self.fixture()
        entries[1] = {'unit_index': 1, 'assigned': True, 'identity_quote': '甲项目',
            'identity_occurrence': 1, 'why': '可能承接', 'confidence': .8}
        result, issues = apply(source, units, segments, {'contexts': entries})
        self.assertTrue(issues)
        self.assertNotIn('object_quote', result[1])


if __name__ == '__main__':unittest.main()
