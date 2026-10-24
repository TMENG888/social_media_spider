import copy
import unittest
from unittest.mock import Mock
import delivery_v6 as v
from test_delivery_v4 import fixture, TAG, BUS


class CoverageAndMapping(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tax=v.base.load_taxonomy(v.legacy.TAXONOMY)
        cls.index=v.registry(cls.tax,v.base.T2)
        cls.tags={t['tag_id']:t for t in cls.tax}

    def raw(self):
        return {'units':[{'labels':[{'choice_key':'D0165'}]}],
                'coverage':{'supported_keys':['D0165'],
                    'unsupported_keys':[k for k in self.index if k!='D0165'],
                    'ambiguous':[],'confidence':.95,'issues':[]}}

    def test_complete_applicable_catalogues(self):
        for topic,n in [(v.base.T1,323),(v.base.T2,580)]:
            cat=v.catalogue(self.tax,topic)
            self.assertEqual(n,len(cat))
            self.assertEqual(n,len({t['choice_key'] for t in cat}))
            self.assertTrue(all(set(t)=={'choice_key','标签强调方向','打标说明','标签对象路径'} for t in cat))
            self.assertTrue(all(len(t['标签对象路径'])==5 for t in cat))

    def test_fixed_key_backfill(self):
        key,reason=v.resolve_selection({'choice_key':'D0165'},self.index)
        self.assertEqual(self.index[key]['tag_id'],'VOC-0165')

    def test_unique_bare_name_recovery(self):
        key,_=v.resolve_selection({'direction':'容积率'},v.registry(self.tax,v.base.T1))
        self.assertEqual(key,'D0165')

    def test_bare_name_ambiguous_across_land_and_product(self):
        self.assertIsNone(v.resolve_selection({'direction':'容积率'},self.index)[0])

    def test_ambiguous_scale_no_guess(self):
        self.assertIsNone(v.resolve_selection({'direction':'尺度'},self.index)[0])

    def test_unknown_key_no_name_fallback(self):
        self.assertIsNone(v.resolve_selection({'choice_key':'D9999','direction':'容积率'},self.index)[0])

    def test_full_coverage(self):
        self.assertEqual([],v.coverage_check(self.raw(),self.index))

    def test_missing_branch_blocked(self):
        raw=self.raw();raw['coverage']['unsupported_keys'].pop()
        self.assertTrue(any('遗漏' in s for s in v.coverage_check(raw,self.index)))

    def test_overlap_partition_blocked(self):
        raw=self.raw();raw['coverage']['unsupported_keys'].append('D0165')
        self.assertTrue(any('重复' in s for s in v.coverage_check(raw,self.index)))

    def test_supported_not_selected_blocked(self):
        raw=self.raw();raw['units'][0]['labels']=[]
        self.assertTrue(any('不一致' in s for s in v.coverage_check(raw,self.index)))

    def test_review_cannot_silently_drop_draft_label(self):
        draft={'units':[{'labels':[{'choice_key':'D0165'}]}]}
        self.assertTrue(v.removal_check(draft,{'units':[]},self.index))

    def test_justified_correction_does_not_union_false_tag(self):
        draft={'units':[{'labels':[{'choice_key':'D0032'}]}]}
        reviewed={'units':[],'removed_draft_labels':[{'choice_key':'D0032','reason':'原文只询问验资300万，未陈述本人预算'}]}
        self.assertEqual([],v.removal_check(draft,reviewed,self.index))
        self.assertEqual(set(),v.selection_keys(reviewed,self.index))

    def test_removal_reason_must_match_change(self):
        draft={'units':[{'labels':[{'choice_key':'D0165'}]}]}
        reviewed={'units':[],'removed_draft_labels':[{'choice_key':'D0032','reason':'不是预算'}]}
        self.assertTrue(v.removal_check(draft,reviewed,self.index))

    def test_relocated_same_label_not_forced_to_remove(self):
        draft={'units':[{'labels':[{'choice_key':'D0165','evidence_start_id':1}]}]}
        reviewed={'units':[{'labels':[{'choice_key':'D0165','evidence_start_id':3}]}]}
        self.assertEqual([],v.removal_check(draft,reviewed,self.index))

    def test_context_club_distant_valid(self):
        context='臻澐的会所。25米恒温泳池。书墙沙龙。来宾交流。茶室、棋牌室。'
        for tid in ['VOC-0380','VOC-0379']:
            self.assertEqual('supported',v.evidence_guard('茶室、棋牌室。',self.tags[tid],context)[0])

    def test_marketing_comma_does_not_erase_installed_device(self):
        self.assertEqual('supported',v.evidence_guard('客厅安装中央空调，建筑面积87平方米，私信预约看房',self.tags['VOC-0234'])[0])

    def test_marketing_only_rejected(self):
        self.assertEqual('rejected',v.evidence_guard('私信预约看房',self.tags['VOC-0234'])[0])

    def test_unpunctuated_fact_with_marketing_kept(self):
        text='双阳台+LDKG一体化设计总价400-500万级兴趣伙伴可扫码对接销售咨询'
        self.assertEqual('supported',v.evidence_guard(text,self.tags['VOC-0206'])[0])
        self.assertEqual('supported',v.evidence_guard('客厅宽8.5米可扫码预约看房',self.tags['VOC-0203'])[0])

    def test_whole_area_not_dining_area(self):
        tag=next(t for t in self.tax if t['emphasis']=='餐厅·尺度')
        self.assertEqual('rejected',v.evidence_guard('餐厅宽敞，整套建筑面积160平方米',tag)[0])

    def test_living_height_kept(self):
        self.assertEqual('supported',v.evidence_guard('客厅挑高6.1米，可改成两层',self.tags['VOC-0203'])[0])

    def test_master_cannot_be_secondary(self):
        tag=next(t for t in self.tax if t['tag_id']=='VOC-0216')
        self.assertEqual('rejected',v.evidence_guard('主卧面积25平方米',tag,'此前介绍次卧。')[0])

    def test_highway_not_entrance(self):
        tag=next(t for t in self.tax if t['l4']=='高速入口')
        self.assertEqual('rejected',v.evidence_guard('邻近高速，会不会吵？',tag)[0])

    def test_verification_deposit_not_budget(self):
        self.assertEqual('rejected',v.evidence_guard('看房要验资吗？300w？',self.tags['VOC-0032'])[0])

    def test_username_is_not_first_person_budget(self):
        text='【父评论｜我的名字就是王美丽】看房要验资吗？300w？【子评论1｜幸福小猫咪】对，验呗，看了又不是必须买'
        for tid in ['VOC-0032','VOC-0019']:
            self.assertEqual('rejected',v.evidence_guard(text,self.tags[tid])[0])

    def test_sales_not_customer_stage(self):
        for tid in ['VOC-0028','VOC-0029']:
            self.assertEqual('rejected',v.evidence_guard('现有内部独家优惠房源，想要的打招呼，我发您优惠政策',self.tags[tid])[0])

    def test_full_input_unchanged_and_independent_review(self):
        doc,u,_=fixture();segments=v.base.evidence_segments(doc['text'],doc['kind'])
        raw={'units':[dict(u,source_start_id=1,source_end_id=len(segments),labels=[{
            'choice_key':'D'+TAG['tag_id'].split('-')[-1],'evidence_start_id':1,'evidence_end_id':len(segments),
            'why':'明确配置中央空调','confidence':.99}])],
            'coverage':{'supported_keys':['D'+TAG['tag_id'].split('-')[-1]],'unsupported_keys':[],'ambiguous':[],'confidence':.99}}
        runner=Mock();runner.call.side_effect=[(raw,{'status':'success'}),(raw,{'status':'success'})]
        v.process_document(doc,[TAG],BUS,runner)
        self.assertEqual(2,runner.call.call_count)
        first=runner.call.call_args_list[0].args[1];second=runner.call.call_args_list[1].args[1]
        self.assertEqual(doc['text'],''.join(s['text'] for s in first['source_segments']))
        self.assertEqual(first['label_catalog'],second['label_catalog'])
        self.assertIn('draft',second)

    def test_review_failure_not_auto_pass(self):
        doc,_,_=fixture();runner=Mock();runner.call.side_effect=[({'units':[]},{'status':'success'}),(None,{'status':'failed'})]
        r=v.process_document(doc,[TAG],BUS,runner)
        self.assertFalse(r['complete']);self.assertEqual(2,len(r['calls']))

    def test_no_dictionary_mapping_error_silent(self):
        raw={'units':[{'labels':[{'direction':'尺度'}]}]}
        mapped,issues=v.canonicalize(raw,self.index)
        self.assertFalse(mapped['units'][0]['labels'])
        self.assertTrue(mapped['units'][0]['uncertainties'])

    def test_smoke_cannot_pass_with_known_omission(self):
        result={'document':{'record_id':'T2-75359'},'rows':[]}
        errors=v.smoke_anchor_errors([result])
        self.assertTrue(any('VOC-0165' in e and '仍遗漏' in e for e in errors))

    def test_auth_failure_not_reported_as_proven_omission(self):
        r={'document':{'record_id':'T2-75359'},'rows':[],'calls':[{'status':'failed'}]}
        errors=v.smoke_anchor_errors([r])
        self.assertTrue(any('无法评估' in e for e in errors))
        self.assertFalse(any('T2-75359：仍遗漏' in e for e in errors))

    def test_unknown_usage_not_zero(self):
        d={'summary':{'tokens':0,'estimated_yuan':0},'calls':[{'source_type':'文章','total_tokens':None,'estimated_yuan':None}],'tables':{}}
        v.expose_unknown_totals(d)
        self.assertIsNone(d['summary']['tokens'])
        self.assertIsNone(d['summary']['estimated_yuan'])

    def test_comment_not_split_after_review(self):
        doc,u,_=fixture('评论')
        raw={'units':[u,u]}
        payload=v.legacy.request_payload(doc,[TAG],BUS)
        result=v.assemble(doc,[TAG],BUS,raw,{'status':'success'},payload,[],True)
        self.assertFalse(result['complete'])
        self.assertFalse(result['rows'])


if __name__=='__main__':unittest.main()
