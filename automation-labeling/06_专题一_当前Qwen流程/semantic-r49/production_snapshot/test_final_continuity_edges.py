import copy
import unittest
from final_continuity_edges import apply,catalog


class ContinuityEdges(unittest.TestCase):
    def setUp(self):
        self.plan={'units':[{'source_start_id':i+1,'source_end_id':i+1,'relevant':True,'project_name':n,
                            'project_ids':[n],'labels':[{'old':i}],'summary':'旧摘要'} for i,n in enumerate(['甲','乙','乙'])]}
        self.response={'edges':[{'edge_key':f'EDGE-{i:04d}','decision':'comparison','theme':'floorplan',
                                'objects':'甲乙户型','why':'连续参数与解释','confidence':.95} for i in range(2)]}
    def test_actual_production_indices_not_model_group_arrays(self):
        out,issues=apply(self.plan,self.response,'北京臻澐项目口碑')
        self.assertFalse(issues);self.assertEqual(1,len(out['units']))
        u=out['units'][0];self.assertEqual((1,3),(u['source_start_id'],u['source_end_id']))
        self.assertEqual(['甲','乙'],u['project_ids']);self.assertEqual([],u['labels']);self.assertIsNone(u['summary'])
        self.assertEqual(3,len(self.plan['units']))
    def test_missing_or_duplicate_keys_fail_closed(self):
        for keys in (['EDGE-0000'],['EDGE-0000','EDGE-0000'],['EDGE-0000','EDGE-0002']):
            r=copy.deepcopy(self.response);r['edges']=[dict(r['edges'][0],edge_key=k) for k in keys]
            self.assertTrue(apply(self.plan,r,'北京臻澐项目口碑')[1])
    def test_transitive_different_themes_not_silently_joined(self):
        r=copy.deepcopy(self.response);r['edges'][1]['theme']='transport'
        self.assertTrue(apply(self.plan,r,'北京臻澐项目口碑')[1])
    def test_keep_boundary_preserves_distinct_topic(self):
        r=copy.deepcopy(self.response);r['edges'][1]['decision']='keep'
        self.assertEqual(2,len(apply(self.plan,r,'北京臻澐项目口碑')[0]['units']))
    def test_t1_and_same_object_metadata_conflicts_rejected(self):
        self.assertTrue(apply(self.plan,self.response,'全国地产设计产品力监测')[1])
        r=copy.deepcopy(self.response)
        for e in r['edges']:e['decision']='same_object'
        self.assertTrue(apply(self.plan,r,'北京臻澐项目口碑')[1])
    def test_invalid_boolean_confidence_is_not_number(self):
        r=copy.deepcopy(self.response);r['edges'][0]['confidence']=True
        self.assertTrue(apply(self.plan,r,'北京臻澐项目口碑')[1])
    def test_catalog_is_all_adjacent_pairs(self):
        self.assertEqual([('EDGE-0000',0,1),('EDGE-0001',1,2)],
                         [(e['edge_key'],e['left_unit_index'],e['right_unit_index']) for e in catalog(['甲','乙','丙'])])


if __name__=='__main__':unittest.main()
