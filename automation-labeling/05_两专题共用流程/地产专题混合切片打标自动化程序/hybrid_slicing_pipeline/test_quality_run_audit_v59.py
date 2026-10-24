import unittest
from quality_run_audit_v59 import scope_check


class ScopeAuditTests(unittest.TestCase):
    def setUp(self):
        self.sample = {'documents': [{'record_id': 'article-A'}, {'record_id': 'comment-B'}]}

    def test_empty_output_cannot_hide_missing_sources(self):
        report = scope_check({'results': []}, self.sample)
        self.assertEqual(report['missing_sources'], ['article-A', 'comment-B'])

    def test_saved_but_incomplete_not_completion(self):
        result = {'document': {'record_id': 'article-A'}, 'complete': False}
        report = scope_check({'results': [result]}, self.sample)
        self.assertEqual(report['incomplete_sources'], ['article-A'])

    def test_duplicate_source_does_not_replace_missing_comment(self):
        result = {'document': {'record_id': 'article-A'}, 'complete': True}
        report = scope_check({'results': [result, result]}, self.sample)
        self.assertEqual(report['duplicate_source_ids'], ['article-A'])
        self.assertEqual(report['missing_sources'], ['comment-B'])


if __name__ == '__main__':
    unittest.main()
