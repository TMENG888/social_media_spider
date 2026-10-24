import unittest
from types import SimpleNamespace as NS
from unittest.mock import patch
import project_relation_check_v63 as relation
import article_scope_v63 as scope
from comment_identity_protocol_v59 import catalogs


class ProjectRelationTests(unittest.TestCase):
    def setUp(self):
        self.cc, self.pc = catalogs('询问乙地块', '甲项目与乙地块对比')
        self.targets = [{'name': '甲项目', 'evidence': {'mode': 'parent_relation'}}]

    def test_explicitly_rejected_relation_not_inherited(self):
        raw = {'checks': [{'target_index':0,'confirmed':False,
            'comment_keys':[self.cc[0]['source_key']], 'parent_relation_keys':[self.pc[0]['source_key']],
            'why':'评论明确乙而非甲','confidence':.99}]}
        kept, errors = relation.apply('询问乙地块','甲项目与乙地块对比',self.targets,raw)
        self.assertEqual(kept,[])
        self.assertIn('评论明确乙而非甲', errors[0])

    def test_wrong_namespace_rejected_even_if_confident(self):
        raw = {'checks': [{'target_index':0,'confirmed':True,
            'comment_keys':[self.pc[0]['source_key']], 'parent_relation_keys':[self.pc[0]['source_key']],
            'why':'声称有据','confidence':1}]}
        self.assertFalse(relation.apply('询问乙地块','甲项目与乙地块对比',self.targets,raw)[0])

    def test_duplicate_indices_cannot_hide_missing_target(self):
        raw = {'checks': [{'target_index':0},{'target_index':0}]}
        self.assertFalse(relation.apply('询问乙地块','甲项目与乙地块对比',self.targets*2,raw)[0])


class ScopeTests(unittest.TestCase):
    def pipeline(self):
        base = NS(load_taxonomy=lambda path: [], T1='T1')
        v = NS(legacy=NS(TAXONOMY='not-read',interval=lambda a,b,c:'规划公园2.1万平方米'),
               registry=lambda t,topic:{'D1':{'l1':'产品','emphasis':'景观面积','instruction':'记录景观面积'}})
        return NS(p=NS(v=v,base=base))

    def test_relevant_fact_not_dropped_as_marketing(self):
        key=scope.source_catalog('规划公园2.1万平方米')[0]['source_key']
        first={'relevant':False,'meaningful_product_fact':False,'applicable_choice_keys':[],
               'source_keys':[key],'why':'营销','confidence':.99}
        second=dict(first,relevant=True,meaningful_product_fact=True,
                    applicable_choice_keys=['D1'],why='有具体面积')
        values=[(first,[{'request_key':'1'}],[],[]),(second,[{'request_key':'2'}],[],[])]
        with patch.object(scope,'bounded',side_effect=values):
            excluded,out,audit,metric=scope.review({'topic':'T1'},
                {'source_start_id':1,'source_end_id':1,'relevant':False},[],None,self.pipeline())
        self.assertFalse(excluded)
        self.assertTrue(out['relevant'])
        self.assertEqual(metric['recovery_call']['request_key'],'2')

    def test_uncertainty_cannot_become_confirmed_exclusion(self):
        key=scope.source_catalog('规划公园2.1万平方米')[0]['source_key']
        first={'relevant':False,'meaningful_product_fact':False,'applicable_choice_keys':[],
               'source_keys':[key],'why':'不确定','confidence':.5}
        with patch.object(scope,'bounded',return_value=(first,[{'request_key':'1'}],[],[])):
            excluded,out,audit,metric=scope.review({'topic':'T1'},
                {'source_start_id':1,'source_end_id':1},[],None,self.pipeline())
        self.assertFalse(excluded)
        self.assertTrue(out['uncertainties'])


if __name__=='__main__':unittest.main()
