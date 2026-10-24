import unittest
import semantic_prose_recovery_v59 as v


class ProseRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.source = '入口门庭高约10米。'
        self.keys = [e['source_key'] for e in v.source_catalog(self.source)]

    def generated(self, prose):
        return {'prose': prose, 'claims': [{'text': prose, 'source_keys': self.keys}],
                'confidence': .95, 'why': '原文支持'}

    def reviewed(self):
        return {'claims': [{'text': '入口门庭约10米高', 'source_keys': self.keys,
                           'supported': True, 'why': '数值对象一致'}],
                'all_assertions_checked': True, 'faithful': True, 'core_covered': True,
                'rewritten': True, 'confidence': .95, 'why': '原文支持'}

    def test_product_exact_copy_rejected_even_short(self):
        self.assertTrue(v.validate_generated(self.source, 'practice', self.generated(self.source)))

    def test_summary_short_complete_allowed(self):
        self.assertEqual(v.validate_generated(self.source, 'summary', self.generated(self.source)), [])

    def test_unknown_source_key_not_evidence(self):
        raw = self.generated('设置约10米高的入口门庭。')
        raw['claims'][0]['source_keys'] = ['invented']
        self.assertTrue(v.validate_generated(self.source, 'practice', raw))

    def test_independent_unsupported_cannot_pass(self):
        raw = self.reviewed(); raw['claims'][0]['supported'] = False
        self.assertTrue(v.validate_review(self.source, 'practice', '门庭约10米高。', raw))

    def test_empty_claims_not_auto_pass(self):
        raw = self.reviewed(); raw['claims'] = []
        self.assertTrue(v.validate_review(self.source, 'summary', '门庭约10米高。', raw))

    def test_missing_core_is_not_success(self):
        raw = self.reviewed(); raw['core_covered'] = False
        self.assertTrue(v.validate_review(self.source, 'summary', '门庭约10米高。', raw))

    def test_confidence_boundary(self):
        raw = self.reviewed(); raw['confidence'] = .899
        self.assertTrue(v.validate_review(self.source, 'summary', '门庭约10米高。', raw))
        raw['confidence'] = .9
        self.assertEqual(v.validate_review(self.source, 'summary', '门庭约10米高。', raw), [])


if __name__ == '__main__':
    unittest.main()
