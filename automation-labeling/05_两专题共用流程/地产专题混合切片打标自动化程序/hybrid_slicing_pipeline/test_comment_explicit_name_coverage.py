import copy
import unittest
import comment_explicit_name_coverage as coverage


class ExplicitNameCoverage(unittest.TestCase):
    def setUp(self):
        self.source='【父评论｜东湖雅苑销售】我住南湖新城，我们和西湖雅苑一个在东边一个在西边。'
        self.catalog=coverage.sources.source_catalog(self.source)
        key=next(e['source_key'] for e in self.catalog if '我住南湖新城' in e['text'])
        self.response={'mentions':[{'name':name,'source_key':key,'quote':'我住南湖新城，我们和西湖雅苑一个在东边一个在西边。',
            'why':'正文明确是居住小区','confidence':.95} for name in ('南湖新城','西湖雅苑')],
            'coverage_complete':True,'confidence':.95}

    def test_grounded_external_names_not_limited_to_business_candidates(self):
        original=copy.deepcopy(self.response)
        targets,issues=coverage.validate(self.response,self.catalog,[])
        self.assertFalse(issues);self.assertEqual(['南湖新城','西湖雅苑'],[t['name'] for t in targets])
        self.assertEqual(original,self.response)
        self.assertTrue(all('id' not in t and 'sentiment' not in t for t in targets))

    def test_nickname_is_not_project_evidence(self):
        self.response['mentions'][0].update(name='东湖雅苑',quote=self.source)
        targets,issues=coverage.validate(self.response,self.catalog,[])
        self.assertTrue(issues);self.assertNotIn('东湖雅苑',[t['name'] for t in targets])

    def test_fabricated_quote_rejected(self):
        self.response['mentions'][0]['quote']='南湖新城有航空噪音'
        self.assertTrue(coverage.validate(self.response,self.catalog,[])[1])

    def test_missing_confidence_not_defaulted(self):
        del self.response['mentions'][0]['confidence']
        self.assertTrue(coverage.validate(self.response,self.catalog,[])[1])

    def test_incomplete_coverage_remains_visible(self):
        self.response['coverage_complete']=False
        self.assertIn('评论明示项目覆盖未完整确认',coverage.validate(self.response,self.catalog,[])[1])

    def test_duplicate_name_not_assigned_twice(self):
        self.response['mentions'].append(copy.deepcopy(self.response['mentions'][0]))
        targets,issues=coverage.validate(self.response,self.catalog,[])
        self.assertEqual(2,len(targets));self.assertTrue(issues)


if __name__=='__main__':unittest.main()
