import copy
import unittest
from final_continuity_merge import apply


class ContinuityMerge(unittest.TestCase):
    def setUp(self):
        self.plan={'units':[{'source_start_id':i+1,'source_end_id':i+1,'relevant':True,
            'project_name':n,'project_ids':[n],'labels':[{'old':i}],'summary':'旧摘要'} for i,n in enumerate(['甲','乙'])]}
        self.response={'groups':[{'unit_indices':[0,1],'kind':'comparison','same_topic':True,'theme':'floorplan',
                                 'objects':'甲乙户型','why':'同一户型层高对比','confidence':.95}]}
    def test_t2_comparison_keeps_both_identities_and_regenerates(self):
        out,issues=apply(self.plan,self.response,'北京臻澐项目口碑')
        self.assertFalse(issues);u=out['units'][0]
        self.assertEqual((1,2),(u['source_start_id'],u['source_end_id']))
        self.assertEqual(['甲','乙'],u['project_ids']);self.assertIsNone(u['project_name'])
        self.assertEqual([],u['labels']);self.assertIsNone(u['summary']);self.assertIsNone(u['object_quote'])
        self.assertEqual(2,len(self.plan['units']))
    def test_t1_cannot_merge_different_project_comparison(self):
        self.assertTrue(apply(self.plan,self.response,'全国地产设计产品力监测')[1])
    def test_same_object_with_conflicting_projects_rejected(self):
        r=copy.deepcopy(self.response);r['groups'][0]['kind']='same_object'
        self.assertTrue(apply(self.plan,r,'北京臻澐项目口碑')[1])
    def test_missing_repeated_noncontiguous_indices_rejected(self):
        for ids in ([1,0],[0,0],[0]):
            r=copy.deepcopy(self.response);r['groups'][0]['unit_indices']=ids
            self.assertTrue(apply(self.plan,r,'北京臻澐项目口碑')[1])
    def test_mixed_relevance_cannot_be_swallowed(self):
        self.plan['units'][1]['relevant']=False
        self.assertTrue(apply(self.plan,self.response,'北京臻澐项目口碑')[1])
    def test_macro_theme_and_low_confidence_rejected(self):
        for patch in ({'theme':'project_overview'},{'confidence':.89},{'confidence':True},{'same_topic':False}):
            r=copy.deepcopy(self.response);r['groups'][0].update(patch)
            self.assertTrue(apply(self.plan,r,'北京臻澐项目口碑')[1])


if __name__=='__main__':unittest.main()
