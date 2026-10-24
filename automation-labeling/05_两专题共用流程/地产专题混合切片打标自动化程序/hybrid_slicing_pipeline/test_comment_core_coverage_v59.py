import unittest
import comment_core_coverage_v59 as v

class CoreCoverageTests(unittest.TestCase):
    def setUp(self):
        self.source='【父评论｜甲】雨后用移动设备清积水。【子评论1｜乙】附近居民才懂。'
        entries=v.source_catalog(self.source)
        self.response={'source_roles':[{'source_key':e['source_key'],'role':'具体事实' if i==0 else '附和',
            'importance':'major' if i==0 else 'noncore','summary_covers':i==0,'why':'实际事件/附和分类'} for i,e in enumerate(entries)],
            'captures_primary_points':True,'why':'主要事件保留，附和允许省略','confidence':.95}
    def test_secondary_acknowledgement_can_be_omitted(self):
        self.assertTrue(v.verify(self.source,'雨后用移动设备清理积水。',self.response)[0])
    def test_acknowledgement_only_not_coverage(self):
        self.response['source_roles'][0]['summary_covers']=False
        self.assertFalse(v.verify(self.source,'附近居民有生活经验。',self.response)[0])
    def test_missing_source_key_classification_fails(self):
        self.response['source_roles'].pop()
        self.assertFalse(v.verify(self.source,'清理积水。',self.response)[0])
    def test_blank_summary_fails_even_model_approves(self):
        self.assertFalse(v.verify(self.source,'',self.response)[0])
    def test_no_major_not_auto_pass(self):
        for r in self.response['source_roles']:r['importance']='noncore'
        self.assertFalse(v.verify(self.source,'附近居民有经验。',self.response)[0])

if __name__=='__main__':unittest.main()
