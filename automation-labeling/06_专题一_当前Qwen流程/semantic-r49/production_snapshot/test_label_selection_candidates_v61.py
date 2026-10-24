import unittest
import label_selection_candidates_v61 as v


class CandidateCanonicalizationTests(unittest.TestCase):
    def test_complete_dictionary_not_keyword_subset(self):
        index = {'D1': {'l1': '产品', 'emphasis': '入口', 'instruction': '入口配置'},
                 'D2': {'l1': '产品', 'emphasis': '花园', 'instruction': '花园配置'}}
        self.assertEqual(len(v.payload('只有入口词', index)['all_applicable_labels']), 2)

    def test_duplicate_label_proposals_keep_all_evidence_before_binding(self):
        raw = {'labels': [{'choice_key': 'D1', 'source_keys': ['A'], 'object_keys': ['O'],
                          'why': '事实1', 'confidence': .95},
                         {'choice_key': 'D1', 'source_keys': ['B'], 'object_keys': ['P'],
                          'why': '事实2', 'confidence': .91}], 'unmatched_facts': []}
        result = v.canonicalize(raw)
        self.assertEqual(len(result['labels']), 1)
        self.assertEqual(result['labels'][0]['source_keys'], ['A', 'B'])
        self.assertEqual(result['labels'][0]['confidence'], .91)
        self.assertEqual(len(raw['labels']), 2)

    def test_distinct_label_ids_not_collapsed(self):
        raw = {'labels': [{'choice_key': 'D1'}, {'choice_key': 'D2'}]}
        self.assertEqual(v.canonicalize(raw), raw)


if __name__ == '__main__':
    unittest.main()
