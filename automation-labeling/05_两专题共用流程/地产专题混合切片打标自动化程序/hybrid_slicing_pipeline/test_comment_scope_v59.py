import unittest
import comment_scope_v59 as v


class CommentScopeTests(unittest.TestCase):
    def setUp(self):
        self.text = '还在比较，先等一等。'
        self.raw = {'kind': 'opinion', 'why': '真实观望态度',
                    'source_keys': [v.source_catalog(self.text)[0]['source_key']], 'confidence': .95}

    def test_opinion_without_product_parameters_retained(self):
        self.assertFalse(v.decision(self.text, self.raw)['exclude'])

    def test_ambiguous_scope_retained_for_review(self):
        self.raw['kind'] = 'uncertain'
        d = v.decision(self.text, self.raw)
        self.assertFalse(d['exclude']); self.assertTrue(d['needs_review'])

    def test_unrelated_low_confidence_not_deleted(self):
        self.raw.update(kind='unrelated', confidence=.89)
        self.assertFalse(v.decision(self.text, self.raw)['exclude'])

    def test_only_grounded_confident_unrelated_excluded(self):
        self.raw['kind'] = 'unrelated'
        self.assertTrue(v.decision(self.text, self.raw)['exclude'])

    def test_failed_protocol_retained_but_not_auto_pass(self):
        d = v.decision(self.text, None, ['API未成功'])
        self.assertFalse(d['exclude']); self.assertTrue(d['needs_review'])

    def test_no_fabricated_key_for_exclusion(self):
        self.raw.update(kind='unrelated', source_keys=['fake'])
        self.assertFalse(v.decision(self.text, self.raw)['exclude'])


if __name__ == '__main__':
    unittest.main()
