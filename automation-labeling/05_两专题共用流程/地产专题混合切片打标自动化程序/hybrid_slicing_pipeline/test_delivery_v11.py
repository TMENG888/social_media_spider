import unittest
import delivery_v11 as p
from unittest.mock import Mock
from unittest.mock import patch


class LosslessPartition(unittest.TestCase):
    def unit(self,a,b):return {'source_start_id':a,'source_end_id':b,'relevant':True,'scope_reason':'住宅事实'}
    def test_complete_article(self):
        self.assertEqual([],p.partition_check({'units':[self.unit(1,2),self.unit(3,5)]},[{}]*5,'文章'))
    def test_no_gaps_or_overlaps(self):
        for pairs in ([(1,2),(4,5)],[(1,3),(3,5)],[(2,5)],[(1,4)]):
            self.assertTrue(p.partition_check({'units':[self.unit(*x) for x in pairs]},[{}]*5,'文章'))
    def test_comment_whole_only(self):
        self.assertEqual([],p.partition_check({'units':[self.unit(1,1)]},[{}],'评论'))
        self.assertTrue(p.partition_check({'units':[self.unit(1,1),self.unit(2,2)]},[{},{}],'评论'))
    def test_irrelevant_span_kept_in_full_partition(self):
        background=dict(self.unit(1,2),relevant=False,scope_reason='平台营销套话')
        self.assertEqual([],p.partition_check({'units':[background,self.unit(3,4)]},[{}]*4,'文章'))
    def test_invalid_source_ids_fail(self):
        for start in ('1',True,None):
            self.assertTrue(p.partition_check({'units':[self.unit(start,1)]},[{}],'文章'))

    def test_free_boundaries_inside_an_unpunctuated_sentence(self):
        text='厨房采用专用烟道止逆阀卫生间地漏设置自动补水'
        raw={'units':[dict(self.unit(1,1),start_quote='厨房采用专用烟道止逆阀'),
                      dict(self.unit(1,1),start_quote='卫生间地漏设置自动补水')]}
        plan,segments,issues=p.quote_partition(raw,text,'文章')
        self.assertEqual([],issues)
        self.assertEqual(text,''.join(s['text'] for s in segments))
        self.assertEqual('卫生间地漏设置自动补水',segments[1]['text'])

    def test_free_boundaries_do_not_guess_duplicate_or_rewritten_quote(self):
        for quote in ('茶室','不存在'):
            raw={'units':[dict(self.unit(1,1),start_quote='甲茶室乙茶室'),dict(self.unit(1,1),start_quote=quote)]}
            self.assertTrue(p.quote_partition(raw,'甲茶室乙茶室','文章')[2])

    def test_repeated_quote_requires_explicit_model_chosen_occurrence(self):
        raw={'units':[dict(self.unit(1,1),start_quote='开头欢迎预约甲主题'),
                      dict(self.unit(1,1),start_quote='欢迎预约',start_occurrence=2)]}
        text='开头欢迎预约甲主题欢迎预约乙主题'
        out,segments,issues=p.quote_partition(raw,text,'文章')
        self.assertEqual([],issues);self.assertEqual('欢迎预约乙主题',segments[1]['text'])
        raw['units'][1]['start_occurrence']=3
        self.assertTrue(p.quote_partition(raw,text,'文章')[2])

    def test_boundary_repair_cannot_drop_unit_or_rewrite_metadata(self):
        plan={'units':[dict(self.unit(1,1),brand='保利')]}
        fixed=p.apply_boundary_repair(plan,{'boundaries':[{'unit_index':0,'start_quote':'原文片头','start_occurrence':1}]})
        self.assertEqual('保利',fixed['units'][0]['brand'])
        self.assertIsNone(p.apply_boundary_repair(plan,{'boundaries':[]}))

    def test_boundary_replan_not_locked_to_hallucinated_previous_count_or_quotes(self):
        payload={'source_text':'厨房配置卫生间配置', 'label_catalog':['all tags'],
                 'source_segments':[{'id':1}], 'projects':[{'id':'P01'}]}
        previous={'units':[dict(self.unit(1,1),start_quote='编造的原文邀约',summary='旧摘要')]}
        result=p.boundary_replan_payload(payload,previous,['起点不存在'])
        self.assertEqual(payload['source_text'],result['source_text'])
        self.assertEqual(payload['projects'],result['projects'])
        self.assertNotIn('label_catalog',result)
        self.assertNotIn('source_segments',result)
        self.assertNotIn('start_quote',result['previous_partition'][0])
        self.assertNotIn('summary',result['previous_partition'][0])
        self.assertIn('可增加、减少、合并、重排',p.BOUNDARY_REPLAN_SYSTEM)
        self.assertIn('第一点/第二点',p.BOUNDARY_REPLAN_SYSTEM)

    def test_free_boundaries_keep_whole_comment_and_spaces(self):
        text='  【父评论】不错【子评论】很吵  '
        raw={'units':[dict(self.unit(1,1),start_quote='  【父评论】不错')]}
        self.assertEqual(text,p.quote_partition(raw,text,'评论')[1][0]['text'])

    def test_comment_boundary_does_not_depend_on_model_quote(self):
        text='【父评论】噪音很吵【子评论】还好'
        raw={'units':[dict(self.unit(1,1),start_quote='模型改写引文')]}
        plan,segments,issues=p.quote_partition(raw,text,'评论')
        self.assertEqual([],issues);self.assertEqual(text,segments[0]['text'])

    def test_model_split_comment_recovers_whole_source_not_first_summary(self):
        text='【父评论】噪音很吵【子评论】价格也贵'
        raw={'units':[dict(self.unit(1,1),summary='噪音很吵',labels=[{'choice_key':'D1'}]),
                      dict(self.unit(2,2),summary='价格也贵',labels=[{'choice_key':'D2'}])]}
        plan,segments,issues=p.quote_partition(raw,text,'评论')
        self.assertEqual([],issues);self.assertEqual(text,segments[0]['text'])
        self.assertEqual(1,len(plan['units']));self.assertEqual([],plan['units'][0]['labels'])
        self.assertIsNone(plan['units'][0]['summary'])
        self.assertEqual(2,len(plan['_original_comment_split']))
        self.assertEqual(2,len(raw['units']))

    def test_scope_prompt_satisfies_json_mode_gateway_contract(self):
        self.assertIn('json',p.SCOPE_SYSTEM.lower())

    def test_confirmed_relevant_unit_not_given_spurious_exclusion_warning(self):
        runner=Mock();runner.call.return_value=({'relevant':True,'why':'住宅配置','scope_evidence_id':1,'confidence':.95},{'status':'success'})
        unit=dict(self.unit(1,1),relevant=True)
        excluded,output,raw,metrics=p.check_exclusion({'kind':'文章'},unit,[{'text':'厨房设置止逆阀'}],runner)
        self.assertFalse(excluded);self.assertFalse(output.get('uncertainties'))

    def test_scope_class_does_not_equate_invitation_to_product_fact(self):
        for kind in ('marketing_invitation','meta_discussion','irrelevant'):
            result=p.resolve_scope_class({'relevant':True,'content_kind':kind},p.p.base.T1)
            self.assertFalse(result['relevant'])
        self.assertTrue(p.resolve_scope_class({'content_kind':'quality_defect'},p.p.base.T1)['relevant'])
        self.assertFalse(p.resolve_scope_class({'content_kind':'opinion'},p.p.base.T1)['relevant'])
        self.assertTrue(p.resolve_scope_class({'content_kind':'opinion'},p.p.base.T2)['relevant'])
        self.assertIsNone(p.resolve_scope_class({'content_kind':'invented'},p.p.base.T1)['relevant'])

    def test_product_subclause_copy_also_requires_rewrite(self):
        source='采用存水弯并将水封高度设置为大于五十毫米，以防止卫生间下水道臭味上返。这是其主要做法。'
        prose='采用存水弯并将水封高度设置为大于五十毫米，以防止卫生间下水道臭味上返。'
        self.assertTrue(p.prose_needs_retry(p.p.base.T1,source,prose))

    def test_scope_evidence_id_retrieves_source_instead_of_generated_quote(self):
        response={'relevant':True,'why':'住宅配置','scope_evidence_id':1,'confidence':.95}
        source='厨房采用高风压抽油烟机。'
        result=p.resolve_scope_reference(response,source)
        self.assertEqual(source,result['direct_quote'])
        self.assertNotIn('direct_quote',response)
        for value in (True,0,2,'1'):
            wrong=dict(response,scope_evidence_id=value)
            self.assertNotIn('direct_quote',p.resolve_scope_reference(wrong,source))

    def test_free_boundary_prompt_does_not_publish_legacy_schema(self):
        self.assertNotIn('"source_start_id":1',p.QUOTE_PLAN_SYSTEM)
        self.assertIn('"start_quote":',p.QUOTE_PLAN_SYSTEM)

    def test_free_boundary_input_removes_old_registry_and_examples(self):
        payload={'source_text':'会所设茶室','source_segments':[{'id':1}],
                 'teaching_examples_only':[{'source_start_id':1}],'label_catalog':['whole_dictionary']}
        previous={'units':[{'start_quote':'会所设茶室','source_start_id':1,'source_end_id':1}]}
        result=p.planning_payload(payload,previous)
        self.assertNotIn('source_segments',result)
        self.assertNotIn('teaching_examples_only',result)
        self.assertEqual(['whole_dictionary'],result['label_catalog'])
        self.assertNotIn('source_start_id',result['previous_partition']['units'][0])
        self.assertEqual(1,previous['units'][0]['source_start_id'])

    def test_reanchor_uses_semantic_segments_not_old_sentence_ids(self):
        text='厨房设烟道止逆阀卫生间设置自动补水'
        segments=[{'id':1,'start':0,'end':9,'text':text[:9]},
                  {'id':2,'start':9,'end':len(text),'text':text[9:]}]
        raw={'units':[{'source_start_id':2,'source_end_id':2,'labels':[
            {'choice_key':'D1','direct_quote':'自动补水','evidence_start_id':99,'evidence_end_id':99}]}]}
        output=p.p.reanchor_literal_evidence(raw,{'text':text,'kind':'文章','semantic_segments':segments})
        self.assertEqual(2,output['units'][0]['labels'][0]['evidence_start_id'])

    def test_local_review_does_not_copy_other_slice_semantic_issues(self):
        raw={'units':[],'coverage_scope':'slice_local','coverage':{'issues':['其他片的对象错误'],'confidence':.5}}
        captured=[]
        def materialize(*args,**kwargs):
            captured.append(kwargs['review_factory']({'labels':[],'self_check':{'pass':True,'confidence':.95,'issues':[]}}))
            return {'document':args[0],'rows':[],'traces':[],'audit':[],'complete':True}
        with patch.object(p.p.v.legacy,'materialize_document',side_effect=materialize):
            p.p.v.assemble({'topic':p.p.base.T1},[],{'projects':[]},raw,{}, {},
                ['其他片的对象错误','全文覆盖审核置信度不足0.90或缺失'],True)
        self.assertTrue(captured[0]['pass']);self.assertEqual([],captured[0]['issues'])
        self.assertEqual(.95,captured[0]['confidence'])

    def test_unresolved_scope_does_not_fabricate_relevance(self):
        runner=Mock();runner.call.return_value=({'relevant':False,'why':'招聘','direct_quote':'不在原文','confidence':.99},{'status':'success'})
        unit=dict(self.unit(1,1),relevant=False)
        exclude,output,raw,metrics=p.check_exclusion({'kind':'文章'},unit,[{'text':'招聘实习生'}],runner)
        self.assertFalse(exclude);self.assertTrue(output['_scope_unresolved'])
        self.assertFalse(output['relevant']);self.assertEqual(2,runner.call.call_count)

    def duplicate_fixture(self):
        units=[dict(self.unit(1,1),labels=[{'choice_key':'D1'},{'choice_key':'D2'}]),
               dict(self.unit(2,2),labels=[{'choice_key':'D1'}])]
        segments=[{'text':'甲项目一梯一户'},{'text':'甲项目独立电梯一梯一户'}]
        pairs=[{'unit_a':0,'unit_b':1,'choice_key':'D1'}]
        check={'checks':[{'pair_id':0,'verdict':'same_fact','keep_unit_index':1,'quote_a':'一梯一户',
                          'quote_b':'独立电梯一梯一户','why':'同甲项目同梯户比，后文详情','confidence':.95}]}
        return units,segments,pairs,check

    def test_duplicate_same_fact_only_removes_one_label_not_source(self):
        units,segments,pairs,check=self.duplicate_fixture()
        result,audit=p.apply_duplicate_checks(units,pairs,check,segments)
        self.assertEqual([{'choice_key':'D2'}],result[0]['labels'])
        self.assertEqual([{'choice_key':'D1'}],result[1]['labels'])
        self.assertEqual(2,len(result));self.assertEqual(1,len(audit))
        self.assertEqual(2,len(units[0]['labels']))

    def test_same_label_different_facts_preserved(self):
        units,segments,pairs,check=self.duplicate_fixture()
        check['checks'][0]['verdict']='different_fact'
        result,audit=p.apply_duplicate_checks(units,pairs,check,segments)
        self.assertEqual(units,result)
        self.assertEqual(1,len(audit))
        self.assertEqual('不同事实保留',audit[0]['status'])

    def test_contradictory_duplicate_reason_cannot_remove(self):
        units,segments,pairs,check=self.duplicate_fixture()
        check['checks'][0]['why']='这些不重复，verdict应为different_fact'
        result,audit=p.apply_duplicate_checks(units,pairs,check,segments)
        self.assertEqual(units[0]['labels'],result[0]['labels'])
        self.assertEqual(units[1]['labels'],result[1]['labels'])
        self.assertEqual('保留待核',audit[0]['status'])

    def test_invalid_object_quote_requires_adjudication(self):
        checks=[{'choice_key':'D1','status':'supported','direct_quote':'茶室','object_quote':'改写的会所名','why':'配置明确'}]
        self.assertEqual(['D1'],p.check_disputes(checks,{'D1':{}},'会所设茶室','会所'))
        checks[0]['object_quote']='会所'
        self.assertEqual([],p.check_disputes(checks,{'D1':{}},'会所设茶室','会所'))

    def test_rejected_candidate_is_reviewed_not_auto_restored(self):
        self.assertEqual(['D1'],p.check_disputes([{'choice_key':'D1','status':'unsupported'}],{'D1':{}},'得房率80%',''))

    def test_unlocated_or_low_confidence_cannot_remove_labels(self):
        for alteration in ({'quote_b':'不存在的事实'},{'confidence':.8},{'keep_unit_index':99}):
            units,segments,pairs,check=self.duplicate_fixture();check['checks'][0].update(alteration)
            result,audit=p.apply_duplicate_checks(units,pairs,check,segments)
            self.assertEqual(units[0]['labels'],result[0]['labels'])
            self.assertEqual(units[1]['labels'],result[1]['labels'])

    def test_project_error_does_not_erase_valid_factual_tag(self):
        unit={'project_ids':['P01'],'project_evidence':[{'id':'P01'}],'_excerpt':'飞机噪音令人困扰',
              'labels':[{'choice_key':'D0157','project_ids':['P01']}]}
        result=p.detach_unsupported_projects({},unit,{'projects':[{'id':'P01','aliases':['臻澐']}]})
        self.assertEqual([],result['project_ids'])
        self.assertEqual('D0157',result['labels'][0]['choice_key'])
        self.assertEqual([],result['labels'][0]['project_ids'])
        self.assertEqual(['P01'],result['labels'][0]['unverified_project_ids'])

    def test_exclusion_without_literal_evidence_cannot_drop_source(self):
        runner=Mock();runner.call.return_value=({'relevant':False,'why':'广告','direct_quote':'不存在','confidence':.99}, {'status':'success'})
        unit=dict(self.unit(1,1),relevant=False)
        exclude,updated,raw,metric=p.check_exclusion({'kind':'文章'},unit,[{'text':'会所设茶室，欢迎来访'}],runner)
        self.assertFalse(exclude);self.assertTrue(updated['_scope_unresolved'])
        self.assertFalse(updated['relevant'])

    def test_confident_grounded_irrelevant_exclusion_keeps_audit(self):
        runner=Mock();runner.call.side_effect=[
            ({'relevant':False,'why':'招聘没有住宅事实','direct_quote':'招聘实习生','confidence':.95}, {'status':'success'}),
            ({'exclude':True,'why':'只有招聘','evidence_ids':[1],'confidence':.95},{'status':'success'})]
        unit=dict(self.unit(1,1),relevant=False)
        exclude,updated,raw,metric=p.check_exclusion({'kind':'文章'},unit,[{'text':'招聘实习生'}],runner)
        self.assertTrue(exclude);self.assertEqual('招聘实习生',raw['direct_quote'])

    def test_candidate_outside_name_must_not_inherit_only_known_project(self):
        doc={'text':'驱鸟炮吓到我了','parent':{'文章内容':'西冉地块有驱鸟炮，保利熙瑞没有驱鸟炮'}}
        response={'targets':[{'name':'西冉地块','comment_quote':'驱鸟炮吓到我了','parent_quote':'西冉地块有驱鸟炮',
                             'why':'父文唯有西冉对应驱鸟炮，不能映射保利','confidence':.95}]}
        targets,issues=p.verified_comment_targets(doc,response,{'projects':[{'id':'C05','name':'保利熙瑞','aliases':['保利熙瑞'],'role':'次核心竞品'}]})
        self.assertEqual([],issues);self.assertEqual('西冉地块',targets[0]['name']);self.assertIsNone(targets[0]['id'])

    def test_unmentioned_project_name_cannot_be_fabricated(self):
        doc={'text':'想去','parent':{'文章内容':'这是公园照片'}}
        response={'targets':[{'name':'北京臻澐','comment_quote':'想去','parent_quote':'公园照片','why':'专题名','confidence':.99}]}
        targets,issues=p.verified_comment_targets(doc,response,{'projects':[]})
        self.assertEqual([],targets);self.assertTrue(issues)

    def test_unqualified_total_price_cannot_be_assumed_shell_price(self):
        tag={'emphasis':'毛坯总价','l1':'产品'}
        self.assertEqual('rejected',p.p.v.evidence_guard('成交总价2572万元',tag)[0])
        self.assertEqual('supported',p.p.v.evidence_guard('毛坯总价2572万元',tag)[0])

    def test_author_environment_complaint_is_not_buying_motivation(self):
        tag={'l1':'客户','l2':'购房动机','l3':'居住痛点','l4':'居住舒适性差','emphasis':'居住舒适性差'}
        self.assertEqual('rejected',p.p.v.evidence_guard('海淀西人民住个新房太命苦了！开发商需要好好想办法解决！',tag)[0])
        self.assertNotEqual('rejected',p.p.v.evidence_guard('我因为飞机噪音太大不考虑买这套了',tag)[0])

    def test_long_or_copied_view_summary_needs_rewrite_not_truncation(self):
        self.assertTrue(p.prose_needs_retry(p.p.base.T2,'原文','摘要'*50))
        self.assertTrue(p.prose_needs_retry(p.p.base.T2,'事实'*30,'事实'*30))
        self.assertFalse(p.prose_needs_retry(p.p.base.T2,'采光不错','采光不错'))
        self.assertTrue(p.prose_needs_retry(p.p.base.T1,'设茶室','设茶室'))


if __name__=='__main__':unittest.main()
