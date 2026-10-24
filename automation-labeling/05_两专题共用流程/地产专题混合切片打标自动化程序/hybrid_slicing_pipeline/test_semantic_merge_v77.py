import copy
import unittest
from unittest.mock import patch
from semantic_merge_v77 import candidates, guarded_merge, identity_conflicts, consolidate

def fixture():
    text='甲项目的105㎡户型设南北双阳台。大玻璃窗改善该户型采光。'
    a='甲项目的105㎡户型设南北双阳台。'; b=text[len(a):]
    tag={'标签路径ID':'VOC-0191','标签编号':190,'一级标签':'产品','二级标签':'户型',
         '三级标签':'通用','四级标签':'采光','五级标签':None,'标签强调方向':'采光'}
    rows=[{'unit_id':str(i),'content_id':'T1-1','证据序号':i+1,'项目':'甲项目',
        '品牌组':'待判断','经营主体':'待判断','城市':'待判断','标签明细':[copy.deepcopy(tag)],
        '原文摘录':q,'具体产品做法':'待核','打标说明':'证据支持采光','备注':'待核','验收状态':'需人工审核'}
        for i,q in enumerate([a,b])]
    return {'document':{'kind':'文章','text':text,'field':'文章内容'},'rows':rows,'traces':[
        {'起点':0,'终点':len(a),'原文证据':a,'标签证据与理由':[],'校验问题':[]},
        {'起点':len(a),'终点':len(text),'原文证据':b,'标签证据与理由':[],'校验问题':[]}],'calls':[]}

class Tests(unittest.TestCase):
    def test_candidates(self):
        self.assertEqual(candidates(fixture()),[(0,1)])
    def test_comments_unchanged(self):
        r=fixture(); r['document']['kind']='评论'
        self.assertEqual(consolidate(r,None),r)
    def test_literal_and_union(self):
        r=fixture(); before=copy.deepcopy(r)
        row,t=guarded_merge(r,[0,1],'甲项目105㎡户型配置南北双阳台和大玻璃窗。','同一户型连续配置')
        self.assertEqual(row['原文摘录'],r['document']['text'])
        self.assertEqual(len(row['标签明细']),1)
        self.assertEqual(t['合并前单元ID'],['0','1'])
        self.assertEqual(r,before)
    def test_distinct_projects(self):
        r=fixture();r['rows'][1]['项目']='乙项目'
        self.assertTrue(identity_conflicts(r['rows']))
        with self.assertRaises(ValueError):guarded_merge(r,[0,1],'配置双阳台','x')
    def test_gap(self):
        r=fixture();r['traces'][1]['起点']+=1
        self.assertEqual(candidates(r),[])
        with self.assertRaises(ValueError):guarded_merge(r,[0,1],'配置双阳台','x')
    def test_new_number(self):
        with self.assertRaises(ValueError):guarded_merge(fixture(),[0,1],'户型面积200㎡。','x')
    def test_copy_empty(self):
        with self.assertRaises(ValueError):guarded_merge(fixture(),[0,1],'','x')
    def test_dictionary_conflict(self):
        r=fixture();r['rows'][1]['标签明细'][0]['四级标签']='不应改写'
        with self.assertRaises(ValueError):guarded_merge(r,[0,1],'双阳台与大玻璃窗。','x')
    def test_missing_identity_retained(self):
        r=fixture();r['rows'][0]['项目']='待判断'
        row,_=guarded_merge(r,[0,1],'甲项目105㎡户型设双阳台与大玻璃窗。','x')
        self.assertEqual(row['项目'],'甲项目')
    def test_innovation_not_silently_lost(self):
        r=fixture();r['rows'][1]['创新类型']='升级'
        with self.assertRaises(ValueError):guarded_merge(r,[0,1],'双阳台与大玻璃窗。','x')
    def test_positive_end_to_end(self):
        r=fixture()
        decisions=[({'merge':True,'same_project':True,'same_object':True,
            'same_fact_or_continuous_explanation':True,'object_quote':'105㎡户型','why':'同一户型','confidence':.95},[],[],[]),
            ({'same_object':True,'all_facts_preserved':True,'project_consistent':True,
              'prose':'甲项目105㎡户型设南北双阳台和大玻璃窗。','why':'有据','confidence':.95},[],[],[]),
            ({'safe':True,'same_object':True,'no_new_facts':True,'no_lost_distinct_fact':True,
              'no_project_mix':True,'prose_supported':True,'why':'同一户型连续配置','confidence':.95},[],[],[])]
        with patch('semantic_merge_v77.review',side_effect=decisions):out=consolidate(r,None)
        self.assertEqual(len(out['rows']),1)
        self.assertEqual(out['rows'][0]['原文摘录'],r['document']['text'])
        self.assertEqual(len(out['rows'][0]['标签明细']),1)
    def test_failed_api_keeps_original(self):
        r=fixture()
        with patch('semantic_merge_v77.review',return_value=(None,[],[],['API failed'])):out=consolidate(r,None)
        self.assertEqual(out['rows'],r['rows'])
    def test_low_confidence_keeps_original(self):
        r=fixture();decision={'merge':True,'same_project':True,'same_object':True,
            'same_fact_or_continuous_explanation':True,'object_quote':'105㎡户型','why':'待核','confidence':.89}
        with patch('semantic_merge_v77.review',return_value=(decision,[],[],[])):out=consolidate(r,None)
        self.assertEqual(out['rows'],r['rows'])

if __name__=='__main__':unittest.main()
