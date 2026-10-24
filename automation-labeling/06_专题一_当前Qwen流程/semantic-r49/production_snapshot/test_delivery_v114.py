import unittest
from unittest.mock import Mock,patch
import delivery_v11 as v
from test_delivery_v4 import fixture,TAG

class GroundedRecovery(unittest.TestCase):
    def test_first_ambiguity_enters_independent_definition_check(self):
        doc,unit,_=fixture(topic=v.p.base.T1)
        unit.update(source_start_id=1,source_end_id=1,labels=[])
        audit={'calls':[],'issues':[],'expected_keys':['D0234'],'supported':[],
            'response':{'decisions':[{'choice_key':'D0234','status':'ambiguous','why':'型号未列'}]}}
        review={'checks':[{'choice_key':'D0234','status':'supported','why':'原文明确配置，不需要型号',
            'direct_quote':'中央空调','confidence':.95}],
            'practice':'住宅精装配置中央空调设备。','summary':None,'prose_supported':True,'prose_confidence':.95,
            'expression_types':['事实介绍'],'emotions':['无态度'],'issues':[],'confidence':.95}
        runner=Mock();runner.call.return_value=(review,{'status':'success'})
        with patch.object(v.branch,'audit',return_value=audit):
            out,report,_=v.check_unit(doc,unit,0,[{'text':doc['text']}],[TAG],runner)
        self.assertEqual(['D0234'],[t['choice_key'] for t in out['labels']])
        self.assertEqual([],report['ambiguous'])
        definition_calls=[c for c in runner.call.call_args_list if 'proposed_labels' in c.args[1]]
        self.assertEqual('D0234',definition_calls[0].args[1]['proposed_labels'][0]['choice_key'])

    def test_topic2_opinion_wrong_exclusion_is_reversed(self):
        doc={'kind':'评论','topic':v.p.base.T2,'text':'不如买石景山','parent':{'文章内容':'住宅对比'}}
        unit={'source_start_id':1,'source_end_id':1,'scope_reason':'购房比较','relevant':True}
        runner=Mock();runner.call.side_effect=[
            ({'relevant':False,'why':'没有产品配置','scope_evidence_id':1,'confidence':.99,'content_kind':'irrelevant'}, {'status':'success'}),
            ({'exclude':False,'why':'专题二购房区位选择评价','evidence_ids':[1],'confidence':.95,
              'positive_facts':[{'kind':'opinion','fact':'建议选择石景山住宅','evidence_ids':[1],
                                'why':'明确购房区位比较','confidence':.95}]},{'status':'success'})]
        exclude,updated,raw,metrics=v.check_exclusion(doc,unit,[{'text':doc['text']}],runner)
        self.assertFalse(exclude);self.assertTrue(updated['relevant'])
        self.assertTrue(updated['uncertainties']);self.assertIn('countercheck_call',metrics)

    def test_whitespace_boundary_keeps_original_source(self):
        text='甲\u00a0户型。乙户型。'
        raw={'units':[{'start_quote':'甲 户型。','relevant':True,'scope_reason':'甲'},
                      {'start_quote':'乙户型。','relevant':True,'scope_reason':'乙'}]}
        out,segments,issues=v.quote_partition(raw,text,'文章')
        self.assertEqual([],issues);self.assertEqual(text,''.join(s['text'] for s in segments))
        self.assertEqual('甲\u00a0户型。',out['units'][0]['start_quote'])

    def test_malformed_project_array_quarantined_not_guessed(self):
        raw={'units':[{'start_quote':'海晏与臻澐','relevant':True,'scope_reason':'两项目对比',
                      'project_ids':[{'id':'C01','evidence':'海晏'}]}]}
        out,segments,issues=v.quote_partition(raw,'海晏与臻澐比较户型','文章')
        self.assertEqual([],issues);self.assertEqual([],out['units'][0]['project_ids'])
        self.assertTrue(out['units'][0]['uncertainties'])

if __name__=='__main__':unittest.main()
