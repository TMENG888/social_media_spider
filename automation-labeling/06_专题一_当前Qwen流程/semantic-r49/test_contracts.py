import sys,unittest
from unittest.mock import patch
sys.dont_write_bytecode=True
import topic1_semantic_pipeline as p
import topic1_identity as identity
import label_candidates as recall
import summary_evidence as summary
import exhaustive_labels as exhaustive
import run_batch300 as batch300
class FakeRunner:
 def __init__(self,answers):self.answers=iter(answers);self.payloads=[]
 def call(self,system,payload,doc,phase,response_schema=None):
  self.payloads.append(payload)
  return next(self.answers),{'status':'success'}
class Contracts(unittest.TestCase):
 def test_proof_completes_dictionary_phrase_but_never_borrows_distant_fact(self):
  text='精装交付，大金中央空调。另一处不配置地暖。'
  end=text.index('调')
  a,b=p.complete_evidence_span(text,0,end,{'l4':'中央空调'})
  self.assertEqual(text[a:b],'精装交付，大金中央空调')
  self.assertNotIn('地暖',text[a:b])
  self.assertEqual(p.complete_evidence_span(text,0,4,{'l4':'地暖'}),(0,4))
 def test_proof_keeps_measurement_units_and_source_codes_whole(self):
  raw='面宽1310mm，户型139B，面积95-128㎡。'
  start=raw.index('310');end=raw.index('mm')+1
  a,b=p.complete_evidence_span(raw,start,end,{'l4':'面宽'})
  self.assertEqual(raw[a:b],'1310mm')
  a,b=p.complete_evidence_span(raw,raw.index('139')+1,raw.index('B'),{})
  self.assertEqual(raw[a:b],'139B')
  a,b=p.complete_evidence_span(raw,raw.index('95'),raw.index('128')+2,{})
  self.assertEqual(raw[a:b],'95-128㎡')
 def test_numeric_completion_does_not_consume_next_table_heading_as_unit(self):
  raw='容积率2.5层高3.3米，176户型待公示。'
  a,b=p.complete_evidence_span(raw,raw.index('高'),raw.index('米')+1,{'l4':'层高'})
  self.assertEqual(raw[a:b],'层高3.3米')
  a,b=p.complete_evidence_span(raw,raw.index('176'),raw.index('户'),{})
  self.assertEqual(raw[a:b],'176')
 def test_attached_grid_proof_is_verbatim_and_completion_is_audited(self):
  raw='甲'*20+'中央空调，后文不是证据。'
  tag={'tag_id':'X','l4':'中央空调'}
  unit={'index':1,'text':raw,'labels':[]}
  p.attach_grid([unit],{'units':[{'index':1,'labels':[{'tag_id':'X','evidence_ids':[1],'reason':'原文设备'}]}]},[tag])
  proof=unit['labels'][0]
  self.assertEqual(proof['quote'],raw[:proof['proof_end']])
  self.assertEqual(proof['quote'],raw[:25])
  self.assertNotIn('后文',proof['quote'])
  # A different grid end that truly clips the phrase is extended, not rewritten.
  raw='甲'*22+'中央空调，后文不是证据。';unit={'index':1,'text':raw}
  p.attach_grid([unit],{'units':[{'index':1,'labels':[{'tag_id':'X','evidence_ids':[1],'reason':'原文设备'}]}]},[tag])
  proof=unit['labels'][0]
  self.assertEqual(proof['quote'],raw[:26]);self.assertIn('evidence_span_completion',proof)
  self.assertEqual(proof['evidence_span_completion']['grid_end'],24)
 def test_positive_model_cannot_bypass_compact_club_scope_guard(self):
  tag={'tag_id':'X','l2':'公区','l3':'会所','l4':'会所功能','l5':'游泳池'}
  unit={'index':1,'text':'会所：1800泳池：8×20'}
  answer={'object_matches':True,'attribute_matches':True,'modality_matches':True,'selected':True,'evidence_ids':[1],'reason':'模型认为字段相邻即包含'}
  proof,verdict=exhaustive.verify_pair({'row':{}},unit,{},tag,FakeRunner([answer]))
  self.assertIsNone(proof)
  self.assertFalse(verdict['selected'])
  self.assertTrue(verdict['model_verdict']['selected'])
 def test_split_configuration_keeps_parent_wide_contract_qualifier(self):
  raw='厨房配品牌设备；卫生间配石材。涉及装标或为同等品牌，具体以写入合同为准。'
  doc={'text':'开头。'+raw+'结尾。'}
  unit={'local_partition_review':{'split':True,'parent_start':3,'parent_end':3+len(raw)}}
  values=p.parent_delivery_qualifiers(doc,unit)
  self.assertEqual(len(values),1)
  self.assertEqual(doc['text'][values[0]['start']:values[0]['end']],values[0]['quote'])
  self.assertIn('以写入合同为准',values[0]['quote'])
  self.assertEqual(p.parent_delivery_qualifiers({'text':'仅卫生间以合同为准。'},{}),[])
 def test_explicit_handover_details_are_recalled_without_all_room_requirement(self):
  tag={'tag_id':'X','l2':'精装','l3':'装修标准','l4':'基础装修标准'}
  self.assertEqual([c['tag_id'] for c in recall.candidates({'text':'卧室软包墙与成品柜均是交付标准。'},[tag])],['X'])
  note=exhaustive.definition_notes([tag])
  self.assertIn('不要求一片同时列齐',note)
 def test_width_notes_preserve_source_mm_without_converting(self):
  note=exhaustive.definition_notes([{'l3':'通用','l4':'面宽'}])
  self.assertIn('m/cm/mm',note);self.assertIn('不换算',note)
 def test_compact_club_scalar_cells_are_not_containment(self):
  tag={'l3':'会所','l4':'会所功能'}
  for raw in ['会所：1800泳池：8×20','会馆面积:1200㎡|健身房:300㎡']:
   self.assertIsNotNone(recall.context_contract(tag,{'text':raw},{'quote':raw}))
  for raw in ['会所：1800㎡，内设泳池：8×20','会所功能包括泳池：8×20','会所：泳池、瑜伽室。']:
   self.assertIsNone(recall.context_contract(tag,{'text':raw},{'quote':raw}))
 def test_local_topic_review_routes_but_does_not_force_splitting(self):
  raw='容积率2.1。园林为台地景观。'
  self.assertGreaterEqual(len(p.topic_refinement_candidates(raw)),2)
  self.assertEqual(p.topic_refinement_candidates('客厅开间5米，进深6米。'),[])
  parent={'index':1,'start':7,'end':7+len(raw),'text':raw}
  runner=FakeRunner([{'cuts':[{'quote':'容积率2.1。','occurrence':1,'theme':'规划'},{'quote':'园林为台地景观。','occurrence':1,'theme':'园林'}]}])
  children=p.refine_topic_partition({'row':{}},[parent],runner)
  self.assertEqual(''.join(c['text'] for c in children),raw)
  self.assertEqual((children[0]['start'],children[-1]['end']),(7,7+len(raw)))
  self.assertEqual(children[0]['end'],children[1]['start'])
  runner=FakeRunner([{'cuts':[{'quote':raw[:8],'occurrence':1,'theme':'连贯做法'}]}])
  self.assertEqual(len(p.refine_topic_partition({'row':{}},[parent],runner)),1)
 def test_pilot_gate_rejects_numeric_only_or_stale_semantic_review(self):
  hashes={b:b*64 for b in 'ABC'}
  record={'version':'candidate','reviewer_type':'codex','approved_for_pilot':True,'critical_errors':0,
          'source_counts':{b:10 for b in 'ABC'},'result_sha256':hashes,'known_limitations':['存在非关键漏标']}
  self.assertEqual(batch300.validate_semantic_release(record,'candidate',hashes),record)
  for changed in [{'critical_errors':1},{'approved_for_pilot':False},{'source_counts':{'A':10,'B':10}},
                  {'result_sha256':{}},{'reviewer_type':'automatic'}]:
   with self.assertRaises(AssertionError):batch300.validate_semantic_release({**record,**changed},'candidate',hashes)
 def test_numeric_prefix_plan_code_not_bare_area_or_technology(self):
  tag={'l2':'户型','l3':'通用','l4':'户型编号'}
  for quote in ['户型127C 3房2厅2卫','127D 4室2厅','户型B2型','编号S1']:
   self.assertIsNone(recall.proof_contract(tag,quote),quote)
  for quote in ['127户型','127㎡户型','智能家居支持5G网络']:
   self.assertIsNotNone(recall.proof_contract(tag,quote),quote)
 def test_bathroom_count_notes_allow_explicit_per_floorplan_values(self):
  note=exhaustive.definition_notes([{'l3':'卫生间','l4':'数量'}])
  self.assertIn('分别有不同',note);self.assertIn('对应关系',note)
 def test_club_status_list_is_not_containment_even_with_cut_proof(self):
  tag={'l3':'会所','l4':'会所功能'}
  raw='高定会所全面投入运营，双泳池、网球场、滨水步道均已开放。'
  self.assertIsNotNone(recall.context_contract(tag,{'text':raw},{'quote':'双泳池、'}))
  self.assertIsNone(recall.context_contract(tag,{'text':'会所内配置双泳池，已全面投入运营。'},{'quote':'会所内配置双泳池，'}))
 def test_specific_sport_cannot_expand_uncertain_abbreviation(self):
  self.assertTrue(summary.unsupported_facility_expansions('综合运动区，恒温篮羽。','设置恒温篮球设施。'))
  self.assertTrue(summary.unsupported_facility_expansions('室内综合球场。','室内排球场。'))
  self.assertFalse(summary.unsupported_facility_expansions('设有羽球馆。','设有羽毛球馆。'))
  self.assertFalse(summary.unsupported_facility_expansions('恒温篮羽。','原文称恒温篮羽。'))
 def test_excluded_self_owned_product_gets_independent_scope_review(self):
  self.assertTrue(p.excluded_product_candidate('本项目自带约2万平方米商业街区，附近另有城市广场。'))
  self.assertFalse(p.excluded_product_candidate('附近有约2万平方米商业街区。'))
  answer={'deliver':True,'reason':'自身商业','practice':'自带约2万平方米商业街区','innovation':'无明确创新类型','level':'I0 无创新判断','innovation_reason':'无'}
  u={'deliver':False,'text':'自带约2万平方米商业街区。','reason':'旧判排除'}
  p.review_excluded_product({'row':{}},u,FakeRunner([answer]))
  self.assertTrue(u['deliver']);self.assertFalse(u['scope_recheck']['previous_deliver'])
 def test_global_design_qualifier_is_exact_source_not_a_configuration(self):
  raw='园林为台地设计。温馨提示：本文建筑、园林、场景均为设计意境参考，最终交付以合同及实景为准。周边配套仅供参考。'
  q=p.source_scope_qualifiers(raw)
  self.assertEqual(len(q),1);self.assertEqual(raw[q[0]['start']:q[0]['end']],q[0]['quote'])
  self.assertEqual(p.source_scope_qualifiers('户型里厨房以合同为准。'),[])
 def test_identity_prunes_other_project_and_adjacent_school_proofs(self):
  current={'id':1,'source_id':'1','field':'正文','quote':'邻近小学由品牌甲地产代建。','is_current_source':True}
  wrong={'id':2,'source_id':'2','field':'正文','quote':'品牌甲地产开发乙城住宅乙苑。','is_current_source':False}
  right={'id':3,'source_id':'3','field':'正文','quote':'甲城住宅甲苑由品牌甲地产开发。','is_current_source':False}
  candidates=[{'source_id':'1','fields':{'文章标题':'甲城住宅甲苑'}},{'source_id':'2','fields':{'文章标题':'乙城住宅乙苑'}},{'source_id':'3','fields':{'文章标题':'甲城住宅甲苑'}}]
  keep,drop=identity.scoped_identity_proofs('住宅甲苑','甲城','entity',[current,wrong,right],candidates,'1')
  self.assertEqual(keep,[right]);self.assertEqual(len(drop),2)
 def test_identity_note_never_repeats_model_alias_claim(self):
  proof={'source_id':'1','field':'正文','quote':'住宅甲由品牌甲地产开发。','is_current_source':True}
  note=identity.identity_note({'brand':'品牌甲','entity':'品牌甲地产','city':''},{'brand':[proof],'entity':[proof],'city':[]})
  self.assertIn(proof['quote'],note);self.assertNotIn('别名',note)
 def test_identity_note_prefers_explicit_project_relation(self):
  generic={'source_id':'2','field':'正文','quote':'品牌甲地产口碑良好。','is_current_source':False}
  direct={'source_id':'3','field':'正文','quote':'甲城住宅甲苑，开发商为品牌甲地产。','is_current_source':False}
  note=identity.identity_note({'brand':'','entity':'品牌甲地产','city':''},{'brand':[],'entity':[generic,direct],'city':[]},'住宅甲苑')
  self.assertIn(direct['quote'],note);self.assertNotIn(generic['quote'],note)
 def test_comparison_target_does_not_license_other_project_paragraph(self):
  wrong={'source_id':'2','field':'正文','quote':'乙城住宅乙苑由品牌甲地产开发。','is_current_source':False}
  right={'source_id':'2','field':'正文','quote':'甲城住宅甲苑由品牌甲地产开发。','is_current_source':False}
  candidates=[{'source_id':'2','fields':{'文章标题':'乙城住宅乙苑与其他盘比较'}}]
  keep,drop=identity.scoped_identity_proofs('住宅甲苑','甲城','entity',[wrong,right],candidates,'1')
  self.assertEqual(keep,[right]);self.assertEqual(drop,[wrong])
 def test_lobby_presence_is_not_reception_management(self):
  tag={'l2':'公区','l3':'大堂','l4':'接待管理'}
  self.assertIsNotNone(recall.proof_contract(tag,'星级入户大堂，私宴厅，行政酒廊全覆盖。'))
  self.assertIsNone(recall.proof_contract(tag,'大堂设接待台，访客须登记。'))
 def test_colisted_community_facilities_are_not_club_rooms(self):
  tag={'l2':'公区','l3':'会所','l4':'会所功能','l5':'游泳池'}
  self.assertIsNotNone(recall.proof_contract(tag,'园区配套：下沉式庭院、私属会所、恒温泳池。'))
  self.assertIsNone(recall.proof_contract(tag,'私属会所内设恒温泳池。'))
  self.assertIsNone(recall.proof_contract(tag,'会所：恒温泳池、健身房。'))
  self.assertIsNone(recall.proof_contract(tag,'对标酒店打造地下会所，恒温泳池、健身房、私宴厅。'))
 def test_package_does_not_imply_compound_equipment(self):
  tag={'l2':'精装','l3':'厨房','l4':'油烟机+燃气灶'}
  self.assertIsNotNone(recall.proof_contract(tag,'厨房配备品牌厨电五件套。'))
  self.assertIsNone(recall.proof_contract(tag,'厨房配备油烟机、燃气灶。'))
 def test_project_total_uses_semantics_not_one_magic_phrase(self):
  tag={'l2':'总图规划','l3':'户数'}
  self.assertIsNone(recall.proof_contract(tag,'这个项目整体只有110户。'))
  self.assertIsNone(recall.proof_contract(tag,'全小区共计222席。'))
  self.assertIsNotNone(recall.proof_contract(tag,'目前在售110户。'))
 def test_possible_personal_remodelling_is_not_present_configuration(self):
  tag={'l2':'户型','l3':'卫生间','l4':'干湿分离'}
  self.assertIsNotNone(recall.proof_contract(tag,'卫生间也是可以作为落地的四分离设计。'))
  self.assertIsNone(recall.proof_contract(tag,'卫生间已经采用四分离设计。'))
 def test_summary_cannot_remove_personal_proposal_modality(self):
  raw='卫生间的话也是可以作为落地的一个四分离的设计。'
  self.assertTrue(summary.personal_proposal_conflicts(raw,'卫生间为落地式四分离设计。'))
  self.assertFalse(summary.personal_proposal_conflicts(raw,'卫生间可作为四分离设计的装修方案。'))
  self.assertFalse(summary.personal_proposal_conflicts('原始四分离设计，后期可以改为四分离设计。','保留原始四分离设计。'))
 def test_status_plus_list_is_not_a_containment_assertion(self):
  raw='高定会所全面投入运营，双泳池、滨水步道、运动场地都已开放。'
  self.assertTrue(summary.colisted_container_conflicts(raw,'高定会所全面投入运营，包含双泳池、滨水步道、运动场地。'))
  self.assertFalse(summary.colisted_container_conflicts(raw,'高定会所全面投入运营；双泳池、滨水步道、运动场地都已开放。'))
  self.assertFalse(summary.colisted_container_conflicts('会所内设双泳池，已运营。','会所包含双泳池。'))
 def test_floorplan_number_and_area_are_not_guessed(self):
  area={'l2':'户型','l3':'通用','l4':'建筑面积'}
  code={'l2':'户型','l3':'通用','l4':'户型编号'}
  self.assertIsNotNone(recall.proof_contract(area,'这个是103户型。'))
  self.assertIsNotNone(recall.proof_contract(code,'这个是103户型。'))
  self.assertIsNone(recall.proof_contract(area,'193平方米全景户型。'))
  self.assertIsNone(recall.proof_contract(code,'A2户型。'))
  self.assertIsNone(recall.proof_contract(code,'户型编号103。'))
  self.assertIsNone(recall.proof_contract(area,'建面约70-119㎡三四居。'))
  self.assertIsNone(recall.proof_contract(area,'在售208㎡/249㎡/318㎡。'))
  self.assertNotIn('103',exhaustive.definition_notes([area]))
  self.assertIsNotNone(recall.proof_contract(area,'140㎡以下超新规将成为绝版产品。'))
 def test_special_space_does_not_take_standard_room_attributes(self):
  tag={'l2':'户型','l3':'特定空间','l4':'功能配置'}
  self.assertIsNotNone(recall.proof_contract(tag,'U型大厨房。'))
  self.assertIsNone(recall.proof_contract(tag,'花房可用于养花、做小茶室。'))
 def test_short_quote_cannot_drop_its_external_referent(self):
  tag={'l2':'物业形态','l3':'别墅'}
  raw='从阳台看出去是另一楼盘的视野，那是当地经典的独栋别墅豪宅。'
  self.assertIsNotNone(recall.context_contract(tag,{'text':raw},{'proof_end':len(raw)}))
  raw='从阳台看出去是公园。再看我们这个项目，是纯叠墅。'
  self.assertIsNone(recall.context_contract(tag,{'text':raw},{'proof_end':len(raw)}))
 def test_dictionary_synonyms_retrieve_without_auto_approval(self):
  tags=[{'tag_id':'X','l2':'精装','l3':'玄关','l4':'玄关柜'}, {'tag_id':'Y','l2':'精装','l3':'阳台','l4':'阳台柜'}]
  candidates=recall.candidates({'text':'进门鞋柜，阳台洗衣机柜。'},tags)
  self.assertEqual({c['tag_id'] for c in candidates},{'X','Y'})
  self.assertTrue(all(not c['evidence_ids'] for c in candidates))
 def test_two_invalid_evidence_proposals_are_rejected_not_adopted(self):
  answer={'object_matches':True,'attribute_matches':True,'modality_matches':True,'selected':True,'evidence_ids':[900],'reason':'无效编号'}
  runner=FakeRunner([answer,answer]);tag={'tag_id':'X','l2':'户型','l3':'通用','l4':'建筑面积'}
  proof,verdict=exhaustive.verify_pair({'row':{}},{'index':1,'text':'English background music only.'},{'tag_id':'X'},tag,runner)
  self.assertIsNone(proof);self.assertEqual(verdict['decision_method'],'bounded_invalid_evidence_rejection')
  self.assertEqual(len(runner.payloads),2)
 def test_advisory_and_unsupported_measurements_are_not_positive_facts(self):
  self.assertIsNotNone(recall.proof_contract({'l3':'通用','l4':'采光'},'去现场重点看三样：抬板后一层采光'))
  self.assertIsNone(recall.proof_contract({'l3':'通用','l4':'采光'},'一层采光充足。'))
  self.assertIsNotNone(recall.proof_contract({'l3':'电梯厅','l4':'梯户比'},'专梯！'))
  self.assertIsNone(recall.proof_contract({'l3':'电梯厅','l4':'梯户比'},'2T2私梯入户'))
  self.assertIsNone(recall.proof_contract({'l3':'电梯厅','l4':'梯户比'},'一梯一户'))
  self.assertIsNotNone(recall.proof_contract({'l3':'大门','l4':'尺度'},'主入口门楼尺度较大'))
  self.assertIsNone(recall.proof_contract({'l3':'大门','l4':'尺度'},'门楼长99.9米，挑高9米'))
 def test_room_width_and_batch_count_do_not_become_whole_project_fields(self):
  self.assertIsNotNone(recall.proof_contract({'l2':'户型','l3':'通用','l4':'面宽'},'客厅面宽4.15米'))
  self.assertIsNone(recall.proof_contract({'l2':'户型','l3':'客厅','l4':'尺度'},'客厅面宽4.15米'))
  self.assertIsNotNone(recall.proof_contract({'l2':'总图规划','l3':'户数'},'首批300多套'))
  self.assertIsNone(recall.proof_contract({'l2':'总图规划','l3':'户数'},'全盘仅237席'))
 def test_exact_prefix_anchor_with_unmodified_source(self):
  text='前言。规划指标\u00a0容积率1.2。立面：陶板。'
  # No fuzzy whitespace normalisation: the exact matching prefix is too short,
  # so this call must fail rather than guess the intended location.
  with self.assertRaises(ValueError):p.resolve_cuts({'text':text},{'cuts':[{'quote':'前言。'},{'quote':'规划指标 容积率1.2。'},{'quote':'立面：陶板。'}]})
 def test_launch_building_identifiers_are_not_project_total(self):
  tag={'l2':'总图规划','l3':'楼栋数'}
  self.assertIsNotNone(recall.proof_contract(tag,'首批楼栋2479栋，共200多套。'))
  self.assertIsNotNone(recall.proof_contract(tag,'本次推出2号楼、4号楼。'))
  self.assertIsNone(recall.proof_contract(tag,'项目共规划6栋洋房；首批推出2号楼。'))
  self.assertIsNone(recall.proof_contract(tag,'楼栋：18栋纯洋房。'))
 def test_start_gap_preserved(self):
  text='前置语。独立门庭为石材。'
  parts=p.resolve_cuts({'text':text},{'cuts':[{'quote':'独立门庭为石材。'}]})
  self.assertEqual(''.join(u['text'] for u in parts),text)
  self.assertEqual(parts[0]['start'],0)
 def test_grid_covers_text(self):
  for text in ['a','，abc。','长'*99,'文本,标点；不规则。\n末尾']:self.assertEqual(''.join(x['text'] for x in p.atoms({'text':text})),text)
 def test_evidence_envelope_no_splicing(self):
  u={'index':1,'text':'第一句，第二句。第三句。','deliver':True}
  p.attach_grid([u],{'units':[{'index':1,'labels':[{'tag_id':'VOC-X','evidence_ids':[1,3],'reason':'test'}]}]},[{'tag_id':'VOC-X'}])
  self.assertEqual(u['labels'][0]['quote'],u['text'])
  self.assertEqual(u['labels'][0]['evidence_ids'],[1,2,3])
 def test_unknown_tag_rejected(self):
  with self.assertRaises(ValueError):p.attach_grid([{'index':1,'text':'原文。'}],{'units':[{'index':1,'labels':[{'tag_id':'VOC-X','evidence_ids':[1],'reason':'test'}]}]},[])
 def test_ambiguous_anchor_rejected(self):
  with self.assertRaises(ValueError):p.resolve_cuts({'text':'重复句子。重复句子。'},{'cuts':[{'quote':'重复句子。','occurrence':5}]})
 def test_summary_only_receives_current_raw_interval(self):
  answer={'deliver':True,'reason':'产品','practice':'石材门庭','innovation':'无明确创新类型','level':'I0 无创新判断','innovation_reason':'无'}
  runner=FakeRunner([answer]);doc={'row':{'文章标题':'某住宅'},'text':'其他片段有999平方米。石材门庭。'}
  p.local_practice(doc,{'text':'石材门庭。'},runner)
  self.assertNotIn('999',str(runner.payloads))
 def test_summary_cross_interval_numbers_fall_back_to_local_verbatim(self):
  answer={'deliver':True,'reason':'产品','practice':'12平方米石材门庭','innovation':'无明确创新类型','level':'I0 无创新判断','innovation_reason':'无'}
  runner=FakeRunner([answer,answer])
  actual=p.local_practice({'row':{}},{'text':'石材门庭。'},runner)
  self.assertEqual(actual['practice'],'石材门庭。')
  self.assertEqual(actual['summary_fallback']['kind'],'verbatim_current_unit')
  self.assertEqual(len(runner.payloads),2)
 def test_unordered_unique_cuts_only_reorder_source_offsets(self):
  text='开场文字。主体甲石材。主体乙玻璃。'
  parts=p.resolve_cuts({'text':text},{'cuts':[{'quote':'主体乙玻璃。'},{'quote':'开场文字。'},{'quote':'主体甲石材。'}]})
  self.assertEqual(''.join(u['text'] for u in parts),text)
  self.assertEqual(parts[0]['anchor_audit']['model_order'],2)
 def test_duplicate_cut_offsets_still_rejected(self):
  with self.assertRaises(ValueError):p.resolve_cuts({'text':'开场文字。主体石材。'},{'cuts':[{'quote':'开场文字。'},{'quote':'开场文字。'}]})
 def test_unsupported_city_is_blank_after_bounded_identity_repair(self):
  doc={'source_id':'1','row':{'文章标题':'中海测试住宅'},'text':'中海测试住宅'}
  unit={'index':1,'start':0,'end':6,'deliver':True,'project':'中海测试住宅'}
  result={'document':doc,'semantic_partition':[unit],'rows':[{'起点':0,'终点':6,'备注':''}]}
  candidate={'source_id':'1','fields':{'文章标题':'中海测试住宅'}}
  answer={'brand':{'value':'中海','evidence_ids':[1]},'entity':{'value':'','evidence_ids':[]},'city':{'value':'深圳','evidence_ids':[1]},'publisher_role':{'value':'身份不明','evidence_ids':[]},'same_project_reason':'同盘'}
  runner=FakeRunner([answer,answer])
  with patch.object(identity,'evidence_candidates',return_value=[candidate]):
   actual=identity.process(result,{'rows':[{'经营主体':'中海地产','品牌组':'中海'}]},runner)
  self.assertEqual(actual['rows'][0]['城市'],'')
  self.assertEqual(actual['rows'][0]['品牌组'],'中海')
  self.assertEqual(len(runner.payloads),2)
  self.assertEqual(actual['identity_audit'][0]['rejected_predictions'][0]['field'],'city')
 def test_identity_grid_keeps_verbatim_field_text(self):
  raw='品牌一。住宅二；主体三。\n'+('长'*260)
  grid=identity.evidence_grid([{'source_id':'1','fields':{'文章内容':raw}}])
  self.assertEqual(''.join(e['quote'] for e in grid),raw)
  self.assertEqual(len({e['id'] for e in grid}),len(grid))
 def test_space_count_does_not_borrow_people_count_or_area(self):
  self.assertIsNotNone(recall.missing_spatial_anchor({'l3':'次卧','l4':'数量'},'20平方米的次卧套房，每一位成员都舒适。'))
  self.assertIsNone(recall.missing_spatial_anchor({'l3':'次卧','l4':'数量'},'有2间次卧。'))
 def test_grid_quote_does_not_cut_number_or_unit(self):
  u={'index':1,'text':'长'*23+'351户，末尾。','deliver':True}
  p.attach_grid([u],{'units':[{'index':1,'labels':[{'tag_id':'VOC-X','evidence_ids':[1],'reason':'数字完整'}]}]},[{'tag_id':'VOC-X'}])
  self.assertTrue(u['labels'][0]['quote'].endswith('351户'))
 def test_fidelity_review_is_local_and_keeps_successful_summary(self):
  u={'text':'石材门庭。','practice':'石材门庭','innovation':'无明确创新类型','level':'I0 无创新判断','innovation_reason':'无'}
  runner=FakeRunner([{'innovation_supported':True,'innovation_issue':'','checks':[{'claim_id':1,'supported':True,'evidence_ids':[1],'reason':'本片明示'}]}])
  audit=p.review_practice({'row':{},'text':'另一片的品牌甲。'},u,runner)
  self.assertFalse(audit['repaired']);self.assertNotIn('品牌甲',str(runner.payloads))
 def test_summary_reviewer_cannot_approve_unchecked_tail(self):
  verdict={'supported':True,'issues':[],'claims':[{'claim':'石材门庭','source_quote':'石材门庭','supported':True}]}
  with self.assertRaises(ValueError):p.check_claim_coverage('石材门庭','石材门庭，配有恒温系统',verdict)
 def test_summary_claim_cannot_use_external_or_rewritten_quote(self):
  verdict={'supported':True,'issues':[],'claims':[{'claim':'石材门庭','source_quote':'另一片的石材门庭','supported':True}]}
  with self.assertRaises(ValueError):p.check_claim_coverage('本片门庭','石材门庭',verdict)
 def test_number_unit_linkage_cannot_be_invented(self):
  self.assertTrue(p.lexical_fidelity_issues('这套143，横厅面宽5米','143㎡户型，面宽5米'))
  self.assertFalse(p.lexical_fidelity_issues('约143㎡，面宽5米','约143㎡户型，面宽5米'))
  self.assertFalse(p.lexical_fidelity_issues('看115/130实际得房','关注130户型实际得房'))
  self.assertTrue(p.lexical_fidelity_issues('128做四房','128平四房'))
  self.assertFalse(p.lexical_fidelity_issues('128平四房','128平四房'))
 def test_conflicting_bathroom_daylight_does_not_become_unconditional(self):
  raw='这个卫生间是暗厕所；另一处又称这次是明侧，具体未明确。'
  self.assertTrue(p.lexical_fidelity_issues(raw,'卫生间采用明卫设计，非暗厕。'))
  self.assertFalse(p.lexical_fidelity_issues(raw,'原文同时提到暗厕所与明侧，归属存疑。'))
 def test_concatenated_floorplans_preserve_property_record_ownership(self):
  raw='主力户型101-111㎡｜3室2厅2卫｜南北通透双阳台121-131㎡｜4室2厅3卫｜双套房观景阳台'
  grid=summary.evidence_blocks(raw)
  self.assertEqual(len(grid),2);self.assertIn('双阳台',grid[0]['text']);self.assertNotIn('双套房',grid[0]['text'])
  self.assertEqual(''.join(x['text'] for x in grid),raw)
  bad={'checks':[{'claim_id':1,'supported':True,'evidence_ids':[2],'reason':'错误借用'}],'innovation_supported':True}
  result=summary.decode(raw,'101-111㎡户型有双套房',grid,bad)
  self.assertFalse(result['supported']);self.assertEqual(result['claims'][0]['decision_method'],'floorplan_object_record_guard')
 def test_explicit_summary_owner_cannot_borrow_another_space_attribute(self):
  self.assertTrue(summary.explicit_owner_conflicts('先看会所，再看门楼，边上有花朵雕塑。','会所拥有花朵雕塑。'))
  self.assertFalse(summary.explicit_owner_conflicts('会所中设有花朵雕塑。','会所拥有花朵雕塑。'))
  self.assertFalse(summary.explicit_owner_conflicts('园林内设叠水景观。','景观设置叠水景观。'))
 def test_fidelity_repair_falls_back_instead_of_accepting_persistent_hallucination(self):
  bad={'supported':False,'issues':['杜拉维特不在原文中']}
  answer={'deliver':True,'reason':'产品','practice':'杜拉维特洁具','innovation':'无明确创新类型','level':'I0 无创新判断','innovation_reason':'无'}
  u={'text':'置高仪、唯宝','practice':'杜拉维特洁具','innovation':'无明确创新类型','level':'I0 无创新判断','innovation_reason':'无'}
  runner=FakeRunner([answer])
  audit=p.review_practice({'row':{}},u,runner)
  self.assertEqual(u['practice'],u['text']);self.assertIn('fallback',audit)
  self.assertEqual(len(runner.payloads),1)
 def test_program_claim_ids_must_all_be_verified(self):
  with self.assertRaises(ValueError):summary.decode('石材门庭。','石材门庭，玻璃幕墙',p.atoms({'text':'石材门庭。'}),{'checks':[{'claim_id':1,'supported':True,'evidence_ids':[1],'reason':'明示'}],'innovation_supported':True})
 def test_no_innovation_is_not_rejected_for_lacking_innovation(self):
  answer={'checks':[{'claim_id':1,'supported':True,'evidence_ids':[1],'reason':'明示'}],'innovation_supported':False,'innovation_issue':'没有首创证据'}
  result=summary.decode('石材门庭。','石材门庭',p.atoms({'text':'石材门庭。'}),answer,check_innovation=False)
  self.assertTrue(result['supported']);self.assertFalse(result['innovation_check_required'])
 def test_evidence_addresses_retrieve_continuous_unmodified_source(self):
  raw='石材门庭，玻璃幕墙。'
  result=summary.decode(raw,'石材门庭',p.atoms({'text':raw}),{'checks':[{'claim_id':1,'supported':True,'evidence_ids':[1],'reason':'明示'}],'innovation_supported':True})
  self.assertEqual(result['claims'][0]['source_quote'],'石材门庭，')
 def test_configuration_brand_and_delivery_fidelity(self):
  self.assertTrue(p.lexical_fidelity_issues('卫生间选用置高仪、唯宝','卫生间选用杜拉维特、唯宝'))
  self.assertTrue(p.lexical_fidelity_issues('园林实景已开放','园林实景交付'))
  self.assertFalse(p.lexical_fidelity_issues('博世厨电，具体以合同为准','博世厨电，以合同为准'))
 def test_facade_water_and_rate_do_not_borrow_neighbor_objects(self):
  self.assertIsNotNone(recall.missing_spatial_anchor({'l2':'公区','l3':'外立面','l4':'性能'},'全屋智能面板，三玻两腔玻璃隔音。'))
  self.assertIsNotNone(recall.missing_spatial_anchor({'l2':'公区','l3':'景观','l5':'水景'},'双水岸萦绕，滨水联排。'))
  self.assertIsNone(recall.missing_spatial_anchor({'l2':'公区','l3':'景观','l5':'水景'},'中央湖景与水景连廊。'))
  self.assertIsNotNone(recall.missing_spatial_anchor({'l2':'户型','l3':'通用','l4':'得房率'},'空间效能105%。'))
if __name__=='__main__':
 unittest.main()
