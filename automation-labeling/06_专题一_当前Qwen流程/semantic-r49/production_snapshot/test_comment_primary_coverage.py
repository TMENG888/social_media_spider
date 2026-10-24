import copy
import unittest
import comment_primary_coverage as coverage
from focused_summary_references import catalog


class CoverageTests(unittest.TestCase):
    def setUp(self):
        self.source='【父评论｜甲】巴士慢但不影响生活。'
        self.response={'coverage':{'captures_primary_points':True,'source_keys':[catalog(self.source)[0]['source_key']],
                                  'why':'保留观点及有限影响','confidence':.95},
                       'checks':[{'status':'unsupported','why':'另一次片段审核决定需独立重审'}]}

    def test_does_not_claim_fact_acceptance_from_coverage(self):
        okay,audit=coverage.verify(self.source,'评论者称巴士慢但不影响生活。',self.response)
        self.assertTrue(okay);self.assertIn('only',audit[0]['review_type'])
        self.assertEqual(self.response['checks'],audit[0]['legacy_fragment_decisions'])

    def test_missing_invalid_unknown_or_false_coverage_rejects(self):
        for key,value in [('source_keys',['unknown']),('captures_primary_points',False),('confidence',.89)]:
            response=copy.deepcopy(self.response);response['coverage'][key]=value
            self.assertFalse(coverage.verify(self.source,'评论者称巴士慢但不影响生活。',response)[0])
        self.assertFalse(coverage.verify(self.source,'观点。',{})[0])

    def test_important_source_qualifier_is_still_mandatory(self):
        self.assertFalse(coverage.verify(self.source,'评论者称巴士很慢。',self.response)[0])


if __name__=='__main__':unittest.main()
