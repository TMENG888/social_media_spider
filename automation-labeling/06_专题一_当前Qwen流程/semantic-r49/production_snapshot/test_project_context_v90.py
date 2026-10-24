import copy
import unittest
import project_context_v90 as v


class ProjectContextTests(unittest.TestCase):
    def setUp(self):
        self.projects = [{'id':'P01','name':'北京臻澐','role':'本品','aliases':['华润臻澐','臻澐']},
            {'id':'C05','name':'保利熙瑞','role':'次核心竞品','aliases':['保利熙瑞']}]
        self.doc = {'kind':'文章','text':'华润臻澐。户型面积504㎡。','title':'华润臻澐504户型',
            'parent':{},'topic':v.T2}
        self.row = {'unit_id':'T2-test-V001','原始摘录':'户型面积504㎡。'}
        self.raw = {'unit_id':self.row['unit_id'],'decision':'known','other_name':'','why':'全文唯一介绍臻澐',
            'confidence':.95,'bindings':[{'project_id':'P01','context_source':'source','identity_quote':'华润臻澐',
                'relation_quote':'户型面积504㎡','mode':'source_context','why':'同一连续户型介绍','confidence':.95}]}

    def test_context_inheritance_does_not_require_local_name(self):
        self.assertEqual(v.validate_decision(self.raw,self.row,self.doc,self.projects),[])

    def test_title_identity_is_accepted_separately(self):
        self.raw['bindings'][0]['context_source']='title'
        self.assertEqual(v.validate_decision(self.raw,self.row,self.doc,self.projects),[])

    def test_wrong_project_with_valid_quote_rejected(self):
        self.raw['bindings'][0]['project_id']='C05'
        self.assertTrue(v.validate_decision(self.raw,self.row,self.doc,self.projects))

    def test_unlocatable_quote_rejected(self):
        self.raw['bindings'][0]['identity_quote']='华润……臻澐'
        self.assertTrue(v.validate_decision(self.raw,self.row,self.doc,self.projects))

    def test_low_confidence_not_force_filled(self):
        self.raw['bindings'][0]['confidence']=.89
        self.assertTrue(v.validate_decision(self.raw,self.row,self.doc,self.projects))

    def test_exact_threshold(self):
        self.raw['confidence']=.9;self.raw['bindings'][0]['confidence']=.9
        self.assertEqual(v.validate_decision(self.raw,self.row,self.doc,self.projects),[])

    def test_punctuation_only_name_normalization(self):
        self.assertTrue(v.mentions('华润·臻澐',self.projects[0]))
        self.assertFalse(v.mentions('臻云酒店',self.projects[0]))

    def test_no_project_cannot_have_binding(self):
        self.raw['decision']='no_project'
        self.assertTrue(v.validate_decision(self.raw,self.row,self.doc,self.projects))

    def test_comment_not_blind_article_context(self):
        self.doc['kind']='评论'
        self.assertTrue(v.validate_decision(self.raw,self.row,self.doc,self.projects))

    def test_existing_scalar_and_array_formats(self):
        for value in ['P01',['P01'],'["P01"]']:
            self.assertEqual(v.project_ids(value),['P01'])
        self.assertEqual(v.project_ids('[]'),[])
        self.assertEqual(v.project_ids([None]),[])

    def test_comment_explicit_parent_relation(self):
        self.doc.update(kind='评论',text='这个户型好大',parent={'文章内容':'华润臻澐户型面积504㎡。'})
        self.row['原始摘录']='这个户型好大'
        self.raw['bindings'][0].update(context_source='parent',identity_quote='华润臻澐',relation_quote='这个户型',mode='parent_relation')
        self.assertEqual(v.validate_decision(self.raw,self.row,self.doc,self.projects),[])

    def test_outside_name_must_exist(self):
        self.raw.update(decision='outside',bindings=[],other_name='某未知项目')
        self.assertTrue(v.validate_decision(self.raw,self.row,self.doc,self.projects))

    def test_resolved_missing_note_removed_other_issue_preserved(self):
        self.row['备注']='原文未明确对应本品或候选竞品，不按文章检索词猜项目；标签仍待核'
        v.with_note(self.row,'项目已补齐',True)
        self.assertEqual(self.row['备注'],'标签仍待核；项目已补齐')

    def test_identity_catalog_keeps_original_punctuation_and_offset(self):
        self.doc['text']='标题后：华润·臻澐。'
        evidence=v.identity_catalog(self.doc,self.projects)
        x=next(x for x in evidence if x['context_source']=='source')
        self.assertEqual(x['identity_quote'],'华润·臻澐')
        self.assertEqual(self.doc['text'][x['start']:x['end']],x['identity_quote'])

    def test_catalog_only_exposes_actually_mentioned_project(self):
        self.assertEqual({x['project_id'] for x in v.identity_catalog(self.doc,self.projects)},{'P01'})

    def test_no_literal_project_catalog_cannot_guess_known(self):
        contract=v.schema([])['properties']['units']['items']['properties']
        self.assertNotIn('known',contract['decision']['enum'])
        self.assertEqual(contract['bindings']['maxItems'],0)

    def test_catalog_materialization_not_model_written_identity(self):
        catalog=v.identity_catalog(self.doc,self.projects)
        x=catalog[0];binding=self.raw['bindings'][0]
        binding.update(identity_key=x['identity_key'],project_id='C05',identity_quote='错误案名')
        v.materialize({'units':[self.raw]},catalog,[self.row],self.doc)
        self.assertEqual(binding['project_id'],'P01')
        self.assertEqual(v.validate_decision(self.raw,self.row,self.doc,self.projects),[])

    def test_does_not_change_prose_or_labels(self):
        row={'unit_id':'T2-x','标签明细':[{'标签路径ID':'VOC-0142'}],'观点摘要':'地铁较近','project_id':[],'备注':''}
        p={'results':[{'document':self.doc,'rows':[row]}]};n=copy.deepcopy(p)
        n['results'][0]['rows'][0]['project_id']=['P01']
        v.assert_preserved(p,n)
        n['results'][0]['rows'][0]['观点摘要']='新内容'
        with self.assertRaises(AssertionError):v.assert_preserved(p,n)


if __name__=='__main__':unittest.main()
