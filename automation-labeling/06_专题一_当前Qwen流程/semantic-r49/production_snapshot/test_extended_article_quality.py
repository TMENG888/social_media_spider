import unittest
import verify_extended_article_quality as v


class IndependentAnchors(unittest.TestCase):
    def test_all_missing_fixed_sources_fail(self):
        r=v.inspect({'results':[]})
        self.assertEqual(10,len(r['errors']))
    def test_exclusion_cannot_hide_incomplete_source(self):
        source={'document':{'record_id':'T1-75177'},'complete':False,'rows':[],
                'excluded_intervals':[{'reason':'无关'}]}
        r=v.inspect({'results':[source]})
        self.assertIn('T1-75177无关样本不强打住宅标签',r['errors'])
    def test_zero_rows_needs_audited_exclusion(self):
        source={'document':{'record_id':'T1-75177'},'complete':True,'rows':[],
                'excluded_intervals':[]}
        self.assertIn('T1-75177无关样本不强打住宅标签',v.inspect({'results':[source]})['errors'])
    def test_supported_exclusion_does_not_need_fake_unit(self):
        source={'document':{'record_id':'T1-75177'},'complete':True,'rows':[],
                'excluded_intervals':[{'reason':'油服招标非地产住宅'}]}
        self.assertNotIn('T1-75177无关样本不强打住宅标签',v.inspect({'results':[source]})['errors'])


if __name__=='__main__':unittest.main()
