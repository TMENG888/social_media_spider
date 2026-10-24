import copy
import unittest
from unittest.mock import MagicMock,patch
import delivery_v8 as v


class GroundedEvidence(unittest.TestCase):
    def doc(self,kind='文章'):
        return {'kind':kind,'text':'会所设茶室，泳池长25米。','title':'容积率1.6，建面180㎡'}

    def response(self):
        return {'units':[{'source_start_id':1,'source_end_id':1,'labels':[{
            'choice_key':'D0380','evidence_start_id':1,'evidence_end_id':1,
            'object_start_id':None,'object_end_id':None,'direct_quote':'会所设茶室','why':'茶室配置明确'}]}],
            'decisions':[{'choice_key':'D0380','status':'supported','why':'明确茶室配置'}]}

    def test_literal_fact_supported(self):
        self.assertEqual([],v.check_grounded(self.response(),self.doc(),{'D0380'}))

    def test_title_fact_cannot_ground_body_tag(self):
        raw=self.response();raw['units'][0]['labels'][0]['direct_quote']='容积率1.6'
        self.assertTrue(any('逐字直接证据' in s for s in v.check_grounded(raw,self.doc(),{'D0380'})))

    def test_comment_complete_not_reply_number(self):
        raw=self.response();raw['units'][0]['source_end_id']=4
        self.assertTrue(v.check_grounded(raw,self.doc('评论'),{'D0380'}))

    def test_missing_candidate_decision_is_error(self):
        self.assertTrue(v.check_grounded(self.response(),self.doc(),{'D0380','D0384'}))

    def test_fake_object_quote_rejected(self):
        raw=self.response();label=raw['units'][0]['labels'][0]
        label.update(object_start_id=1,object_end_id=1,object_quote='父文章有会所')
        self.assertTrue(any('对象证据' in s for s in v.check_grounded(raw,self.doc(),{'D0380'})))

    def test_supported_decision_cannot_disappear(self):
        raw=self.response();raw['units'][0]['labels']=[]
        self.assertTrue(any('不一致' in s for s in v.check_grounded(raw,self.doc(),{'D0380'})))

    def test_first_pass_candidate_survives_recall_audit(self):
        old={'draft':{'units':[{'labels':[{'choice_key':'D0165'}]}]},'reviewed':{'units':[]},'branch_audits':[]}
        self.assertEqual({'D0165'},v.candidate_keys(old,{'D0165':{}}))

    def test_ellipsis_only_when_all_fragments_verbatim_in_order(self):
        self.assertEqual(['会所设茶室','泳池长25米'],v.quote_fragments('会所设茶室...泳池长25米','会所设茶室，泳池长25米。'))
        self.assertIsNone(v.quote_fragments('会所设棋牌室...泳池长25米','会所设茶室，泳池长25米。'))
        self.assertIsNone(v.quote_fragments('泳池长25米...会所设茶室','会所设茶室，泳池长25米。'))

    def test_comment_boundary_fixed_by_whole_source_contract(self):
        raw=self.response();raw['units'][0]['source_end_id']=4
        raw['units'][0]['labels'][0]['evidence_start_id']=4
        fixed=v.reanchor_literal_evidence(raw,self.doc('评论'))
        self.assertEqual([],v.check_grounded(fixed,self.doc('评论'),{'D0380'}))
        self.assertEqual([1,4],fixed['units'][0]['original_model_source_ids'])

    def test_article_reanchor_does_not_change_slice_boundary(self):
        raw=self.response();raw['units'][0]['labels'][0]['evidence_start_id']=4
        fixed=v.reanchor_literal_evidence(raw,self.doc())
        self.assertEqual(1,fixed['units'][0]['source_end_id'])
        self.assertEqual([],v.check_grounded(fixed,self.doc(),{'D0380'}))

    def test_valid_evidence_preserves_context_without_moving_semantic_slice(self):
        raw=self.response();doc={'kind':'文章','text':'整体介绍。会所设茶室。其他景观。'}
        raw['units'][0]['source_end_id']=3
        raw['units'][0]['labels'][0]['evidence_end_id']=3
        fixed=v.reanchor_literal_evidence(raw,doc)
        self.assertEqual(3,fixed['units'][0]['source_end_id'])
        self.assertEqual(1,fixed['units'][0]['labels'][0]['evidence_start_id'])
        self.assertEqual(3,fixed['units'][0]['labels'][0]['evidence_end_id'])
        self.assertEqual([],v.check_grounded(fixed,doc,{'D0380'}))

    def test_clubhouse_context_not_removed_from_following_facility_quote(self):
        raw=self.response();doc={'kind':'文章','text':'臻澐的会所。设有茶室、棋牌室。'}
        raw['units'][0]['source_end_id']=2
        label=raw['units'][0]['labels'][0]
        label.update(direct_quote='设有茶室、棋牌室',evidence_end_id=2)
        fixed=v.reanchor_literal_evidence(raw,doc)
        self.assertEqual((1,2),(fixed['units'][0]['labels'][0]['evidence_start_id'],fixed['units'][0]['labels'][0]['evidence_end_id']))
        self.assertEqual(fixed,v.reanchor_literal_evidence(fixed,doc))

    def test_unlocated_tag_is_explicit_ambiguity_not_silent_loss(self):
        raw=self.response();raw['units'][0]['labels'][0]['direct_quote']='父文章的泳池'
        fixed,deferred=v.defer_unlocated_labels(raw,self.doc(),{'D0380'})
        self.assertEqual(1,len(deferred))
        self.assertEqual([],v.check_grounded(fixed,self.doc(),{'D0380'}))
        self.assertEqual('ambiguous',fixed['decisions'][0]['status'])
        self.assertEqual([],fixed['units'][0]['labels'])

    def test_total_area_does_not_erase_real_living_room_width(self):
        tax=v.base.load_taxonomy(v.v.legacy.TAXONOMY)
        tag=next(t for t in tax if t['tag_id']=='VOC-0203')
        state,_=v.v.evidence_guard('建面约167㎡的下叠横向宽厅达到约8.5米',tag)
        self.assertEqual('supported',state)

    def test_floorplan_bathroom_count_not_erased_by_missing_full_room_word(self):
        tax=v.base.load_taxonomy(v.v.legacy.TAXONOMY)
        tag=next(t for t in tax if t['tag_id']=='VOC-0208')
        self.assertEqual('supported',v.v.evidence_guard('建筑面积190㎡，3+1房2厅2卫',tag)[0])

    def test_floorplan_bathroom_count_cannot_be_used_as_area(self):
        tax=v.base.load_taxonomy(v.v.legacy.TAXONOMY)
        tag=copy.deepcopy(next(t for t in tax if t['tag_id']=='VOC-0208'))
        tag['l4']='尺度'  # Exercise generic object guard, not a new VOC label.
        self.assertEqual('rejected',v.v.evidence_guard('建筑面积190㎡，3+1房2厅2卫',tag)[0])

    def test_chinese_counts_do_not_blank_correct_rewrites(self):
        self.assertFalse(v.base.evidence_numeric_values('8个会所主题，4房2厅')-v.base.evidence_numeric_values('八大主题会所，四房二厅'))
        self.assertTrue(v.base.evidence_numeric_values('5房')-v.base.evidence_numeric_values('四房二厅'))

    def test_chinese_asr_wrong_magnitude_is_not_silently_corrected(self):
        self.assertNotIn('140',v.base.evidence_numeric_values('一百四十亿平'))
        self.assertIn('14000000000',v.base.evidence_numeric_values('一百四十亿平'))

    def test_malformed_unit_does_not_crash_small_repair(self):
        raw={'units':['malformed'],'decisions':[]}
        self.assertEqual((raw,[]),v.repair_decision_partition(raw,self.doc(),set(),{}, {},None))

    def test_literal_quote_recovers_missing_or_wrong_unit_index(self):
        segments=v.base.evidence_segments(self.doc()['text'],'文章')
        units=self.response()['units']
        self.assertEqual(0,v.literal_unit_index('会所设茶室',units,segments,None))
        self.assertEqual(0,v.literal_unit_index('泳池长25米',units,segments,99))

    def test_ambiguous_literal_unit_never_arbitrarily_selected(self):
        segments=v.base.evidence_segments(self.doc()['text'],'文章')
        units=self.response()['units']*2
        self.assertIsNone(v.literal_unit_index('会所设茶室',units,segments,0))
        self.assertIsNone(v.literal_unit_index('标题面积180㎡',units,segments,0))

    def test_per_unit_recovery_keeps_all_grounded_occurrences(self):
        doc={'kind':'文章','text':'甲户型面积100㎡。\n乙户型面积120㎡。'}
        segments=v.base.evidence_segments(doc['text'],'文章')
        units=[{'source_start_id':s['id'],'source_end_id':s['id'],'labels':[]} for s in segments]
        raw={'units':units,'decisions':[{'choice_key':'D0186','status':'ambiguous','why':'未定位'}]}
        placements=[{'direct_quote':s['text'],'unit_index':999,'why':'对应户型的直接面积数值','confidence':.95} for s in segments]
        runner=MagicMock();runner.call.return_value=({'decisions':[{'choice_key':'D0186','status':'supported','why':'各户型面积明确','confidence':.95,'placements':placements}]},{'status':'success'})
        fixed,_=v.repair_decision_partition(raw,doc,{'D0186'},{'D0186':{'tag_id':'VOC-0186'}},{'label_catalog':[{'choice_key':'D0186'}]},runner,{'D0186'})
        self.assertTrue(all(len(u['labels'])==1 for u in fixed['units']))

    def test_bad_total_measurement_does_not_erase_good_housing_area(self):
        doc={'kind':'文章','text':'预售面积76480平方米，户型面积128至234平方米。'}
        raw={'units':[{'source_start_id':1,'source_end_id':1,'labels':[]}],
            'decisions':[{'choice_key':'D0186','status':'ambiguous','why':'未定位'}]}
        placements=[{'direct_quote':quote,'unit_index':0,'why':'面积事实','confidence':.95} for quote in ['预售面积76480平方米','户型面积128至234平方米']]
        runner=MagicMock();runner.call.return_value=({'decisions':[{'choice_key':'D0186','status':'supported','why':'面积明确','confidence':.95,'placements':placements}]},{'status':'success'})
        fixed,_=v.repair_decision_partition(raw,doc,{'D0186'},{'D0186':{'tag_id':'VOC-0186'}},{'label_catalog':[{'choice_key':'D0186'}]},runner,{'D0186'})
        self.assertEqual('户型面积128至234平方米',fixed['units'][0]['labels'][0]['direct_quote'])
        self.assertEqual(1,len(fixed['decisions'][0]['placement_rejections']))
        self.assertIsNone(fixed['decisions'][0]['confidence'])

    def test_multiple_layouts_are_qa_trigger_not_rule_split(self):
        doc={'kind':'文章','text':'建筑面积：190㎡，主卧套间。建筑面积：225㎡，双阳台。'}
        raw={'units':[{'source_start_id':1,'source_end_id':2,'labels':[]}]}
        before=copy.deepcopy(raw)
        self.assertTrue(v.semantic_quality_flags(raw,doc))
        self.assertEqual(before,raw)

    def test_trimmed_original_is_not_product_practice_rewrite(self):
        text='项目标配大金中央空调、中科睿赛新风系统和西门子厨电三件套，体现高端品质。'
        doc={'kind':'文章','text':text}
        raw={'units':[{'source_start_id':1,'source_end_id':1,'practice':text.split('，')[0]}]}
        self.assertTrue(v.semantic_quality_flags(raw,doc))
        raw['units'][0]['practice']='住宅设备包括大金中央空调、中科睿赛新风系统，以及西门子三件套厨电。'
        self.assertEqual([],v.semantic_quality_flags(raw,doc))

    def test_quality_api_failure_retains_evidence_and_blocks_acceptance(self):
        text='项目标配大金中央空调、中科睿赛新风系统和西门子厨电三件套，体现高端品质。'
        doc={'kind':'文章','text':text,'topic':v.base.T1}
        raw={'units':[{'source_start_id':1,'source_end_id':1,'practice':text.split('，')[0],'labels':[{'choice_key':'D0234','direct_quote':'大金中央空调','evidence_start_id':1,'evidence_end_id':1,'why':'设备明确'}]}],
            'decisions':[{'choice_key':'D0234','status':'supported','why':'设备明确'}]}
        runner=MagicMock();runner.call.return_value=(None,{'status':'failed'})
        fixed,_=v.refine_semantic_quality(raw,doc,{'D0234'},{'label_catalog':[{'choice_key':'D0234','tag_id':'VOC-0234'}]},runner)
        self.assertEqual(raw['units'][0]['labels'],fixed['units'][0]['labels'])
        self.assertFalse(fixed['units'][0]['self_check']['pass'])

    def test_independent_rewrite_review_corrects_added_independent_room(self):
        doc={'kind':'文章','text':'设置中西双厨。'}
        raw={'units':[{'source_start_id':1,'source_end_id':1,'practice':'两个独立厨房房间','practice_rewrite_audit':{}}]}
        raw['units'][0]['practice_rewrite_audit']={'source':'test'}
        runner=MagicMock();runner.call.return_value=({'checks':[{'unit_index':0,'supported':False,'confidence':.95,
            'why':'中西双厨不证明独立房间','corrected_practice':'厨房同时提供中式与西式烹饪配置。',
            'claims':[{'fact':'中西双厨配置','quote':'中西双厨'}]}]},{'status':'success'})
        fixed,_=v.verify_practice_grounding(raw,doc,runner)
        self.assertNotIn('独立',fixed['units'][0]['practice'])
        self.assertTrue(fixed['units'][0]['uncertainties'])

    def test_independent_rewrite_review_rejects_foreign_unit_quote(self):
        doc={'kind':'文章','text':'设置中西双厨。'}
        raw={'units':[{'source_start_id':1,'source_end_id':1,'practice':'厨房提供两类烹饪配置','practice_rewrite_audit':{'source':'test'}}]}
        runner=MagicMock();runner.call.return_value=({'checks':[{'unit_index':0,'supported':True,'confidence':.99,
            'claims':[{'fact':'独立厨房','quote':'两个独立厨房'}]}]},{'status':'success'})
        fixed,_=v.verify_practice_grounding(raw,doc,runner)
        self.assertTrue(fixed['units'][0]['uncertainties'])

    def test_external_commercial_label_quarantine_has_explicit_reason(self):
        doc={'kind':'文章','text':'项目与商场一路之隔，商场有超市。'}
        raw={'units':[{'source_start_id':1,'source_end_id':1,'labels':[{'choice_key':'D0418','direct_quote':'商场有超市'}]}],
            'decisions':[{'choice_key':'D0418','status':'supported','why':'超市'}]}
        index={'D0418':{'l1':'产品','l3':'社区商业','instruction':'记录社区商业超市'}}
        runner=MagicMock();runner.call.return_value=({'checks':[{'item_id':0,'status':'unsupported','confidence':.95,
            'why':'外部商场不是住宅公区商业','source_quote':'项目与商场一路之隔'}]},{'status':'success'})
        fixed,_=v.audit_sensitive_object_labels(raw,doc,index,runner)
        self.assertEqual([],fixed['units'][0]['labels'])
        self.assertEqual('ambiguous',fixed['decisions'][0]['status'])
        self.assertTrue(fixed['decisions'][0]['object_alignment_rejections'][0]['original_labels'])

    def test_object_audit_cannot_use_foreign_source_quote_to_delete_label(self):
        doc={'kind':'评论','text':'社区超市很方便。'}
        raw={'units':[{'source_start_id':1,'source_end_id':1,'labels':[{'choice_key':'D0418','direct_quote':'社区超市很方便'}]}],
            'decisions':[{'choice_key':'D0418','status':'supported','why':'超市便利'}]}
        index={'D0418':{'l1':'产品','l3':'社区商业','instruction':'记录社区商业超市'}}
        runner=MagicMock();runner.call.return_value=({'checks':[{'item_id':0,'status':'unsupported','confidence':.99,
            'why':'父文章说是外部商场','source_quote':'父文章中的外部商场'}]},{'status':'success'})
        fixed,_=v.audit_sensitive_object_labels(raw,doc,index,runner)
        self.assertEqual(raw['units'][0]['labels'],fixed['units'][0]['labels'])
        self.assertTrue(fixed['units'][0]['uncertainties'])


class ApiDeadline(unittest.TestCase):
    def test_keepalive_chunks_do_not_extend_attempt_deadline(self):
        connection=MagicMock();response=connection.getresponse.return_value
        response.status=200;response.read1.side_effect=[b' ',b' ',b' ']
        with patch.object(v.base.http.client,'HTTPConnection',return_value=connection),patch.object(v.base.time,'monotonic',side_effect=[0,.1,.2,.9,1.1]):
            with self.assertRaises(TimeoutError):v.base.post_json('http://127.0.0.1/mock',{},'test-placeholder',timeout=1)
        self.assertEqual(2,response.read1.call_count)
        connection.close.assert_called_once()

    def test_normal_reply_preserves_status_and_json(self):
        connection=MagicMock();response=connection.getresponse.return_value
        response.status=200;response.read1.side_effect=[b'{"ok":true}',b'']
        with patch.object(v.base.http.client,'HTTPConnection',return_value=connection):
            reply=v.base.post_json('http://127.0.0.1/mock',{},'test-placeholder')
        self.assertEqual(200,reply.status_code);self.assertEqual({'ok':True},reply.json())


if __name__=='__main__':unittest.main()
