import copy
import unittest
import joint_keyword_supplement_v95 as j
from test_keyword_supplement_v94 import KeywordFallbackTest


class JointKeywordTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tax=j.core.base.load_taxonomy(j.core.DEFAULT_TAXONOMY)
        cls.index=j.core.index_for(cls.tax,j.core.base.T1)

    def fixture(self,text,source='D0380',proof=True):
        result=KeywordFallbackTest.result(self,text)
        result['rows'][0]['标签明细']=[j.core.label_json(self.index[source])]
        if proof:
            quote=text.split('。')[0]
            result['traces'][0]['标签证据与归属']=[{'key':source,'quotes':[quote],'context_quotes':[],
                'attribute_spans':[{'start':0,'end':len(quote),'quote':quote}],'object_spans':[],
                'object':j.k.compile_rule(source,self.index[source])['scope'],'confidence':.95,'reason':'原文有据'}]
        return result

    def ids(self,result):return {t['标签路径ID'] for t in result['rows'][0]['标签明细']}

    def test_continuing_club_from_frozen_tag(self):
        r=self.fixture('会所设有茶室。还配备25米恒温泳池。')
        p=j.process(r,self.tax);self.assertIn('VOC-0384',self.ids(p))
        e=next(e for e in p['joint_keyword_supplement_events'] if e['key']=='D0384')
        self.assertEqual(e['source_label_id'],'VOC-0380');self.assertFalse(e['program_issues'])
        self.assertEqual(e['quotes'],['还配备25米恒温泳池'])

    def test_reverse_cannot_inherit(self):
        self.assertNotIn('VOC-0384',self.ids(j.process(self.fixture('泳池开放。会所设茶室。'),self.tax)))

    def test_label_only_object_needs_raw_proof(self):
        p=j.process(self.fixture('这里配备游泳池。',proof=False),self.tax)
        self.assertNotIn('VOC-0384',self.ids(p))
        self.assertTrue(any(e['key']=='D0384' for e in p['joint_keyword_supplement_deferred']))

    def test_wrong_label_cannot_create_fact(self):
        p=j.process(self.fixture('体育公园设游泳池。',proof=False),self.tax)
        self.assertNotIn('VOC-0384',self.ids(p))

    def test_park_switch_blocks(self):
        p=j.process(self.fixture('会所设茶室。体育公园还配备游泳池。'),self.tax)
        self.assertNotIn('VOC-0384',self.ids(p))

    def test_room_switch_blocks(self):
        p=j.process(self.fixture('会所设茶室。主卧配备空调。'),self.tax)
        self.assertNotIn('VOC-0384',self.ids(p))

    def test_speaker_switch_blocks(self):
        p=j.process(self.fixture('【父评论｜甲】会所设茶室。【子评论1｜乙】这里有游泳池。'),self.tax)
        self.assertNotIn('VOC-0384',self.ids(p))

    def test_new_project_blocks(self):
        p=j.process(self.fixture('会所设茶室。另一个楼盘还配备游泳池。'),self.tax)
        self.assertNotIn('VOC-0384',self.ids(p))

    def test_negation_blocks(self):
        p=j.process(self.fixture('会所设茶室。不设游泳池。'),self.tax)
        self.assertNotIn('VOC-0384',self.ids(p))

    def test_question_blocks(self):
        p=j.process(self.fixture('会所设茶室。配有游泳池吗？'),self.tax)
        self.assertNotIn('VOC-0384',self.ids(p))

    def test_numeric_metadata_never_evidence(self):
        r=self.fixture('这里设施不错。','D0373',False)
        p=j.process(r,self.tax)
        self.assertEqual(self.ids(p),self.ids(r))
        self.assertNotIn('373',j.label_text(r['rows'][0]['标签明细'][0]))

    def test_pure_labels_cannot_supply_attribute(self):
        r=self.fixture('会所整体不错。','D0384',False)
        p=j.process(r,self.tax)
        self.assertNotIn('VOC-0397',self.ids(p))

    def test_source_proof_wrong_offsets_blocks(self):
        r=self.fixture('会所设茶室。还配备游泳池。')
        r['traces'][0]['标签证据与归属'][0]['attribute_spans'][0]['start']=1
        self.assertNotIn('VOC-0384',self.ids(j.process(r,self.tax)))

    def test_source_history_rejection_blocks(self):
        r=self.fixture('会所设茶室。还配备游泳池。')
        r['label_supplement_events']=[{'unit_id':r['rows'][0]['unit_id'],'key':'D0380','处理':'历史否决',
                                      'verdict':'unsupported','confidence':.99,'原因':'对象不符'}]
        self.assertNotIn('VOC-0384',self.ids(j.process(r,self.tax)))

    def test_target_history_rejection_blocks(self):
        r=self.fixture('会所设茶室。还配备游泳池。')
        r['label_supplement_events']=[{'unit_id':r['rows'][0]['unit_id'],'key':'D0384','处理':'历史否决',
                                      'verdict':'unsupported','confidence':.99,'原因':'对象不符'}]
        self.assertNotIn('VOC-0384',self.ids(j.process(r,self.tax)))

    def test_numeric_inheritance_review(self):
        r=self.fixture('厨房配备空调。面积约20㎡。','D0251')
        self.assertNotIn('VOC-0199',self.ids(j.process(r,self.tax)))

    def test_frozen_no_cascade_and_idempotent(self):
        r=self.fixture('会所设茶室。还配备游泳池。');original=copy.deepcopy(r)
        p=j.process(r,self.tax);again=j.process(p,self.tax)
        self.assertEqual(r,original);self.assertEqual(p['rows'],again['rows'])
        self.assertEqual(p['joint_keyword_supplement_events'],again['joint_keyword_supplement_events'])
        self.assertEqual(p['traces'][0]['联合补标初始标签快照'],original['rows'][0]['标签明细'])
        self.assertEqual(len(p['rows'][0]['标签明细']),len(self.ids(p)))

    def test_all_topic_labels_scanned(self):
        p=j.process(self.fixture('会所设茶室。还配备游泳池。'),self.tax)
        self.assertEqual(p['joint_keyword_supplement_coverage']['checked_unit_label_pairs'],323)

    def test_universal_bedrooms_raw_window_and_label_object(self):
        r=self.fixture('整体采用四房四卫全套房设计，每一间卧室均配备独立明卫与观景飘窗。','D0213')
        p=j.process(r,self.tax)
        self.assertIn('VOC-0307',self.ids(p))
        event=next(e for e in p['joint_keyword_supplement_events'] if e['key']=='D0307')
        self.assertEqual(event['object_binding_method'],'原文全称卧室范围覆盖已有卧室对象')

    def test_some_bedrooms_not_universal(self):
        r=self.fixture('整体采用四房四卫全套房设计，部分卧室配备观景飘窗。','D0213')
        self.assertNotIn('VOC-0307',self.ids(j.process(r,self.tax)))

    def test_universal_low_confidence_source_not_automatic(self):
        r=self.fixture('每一间卧室均配备观景飘窗。','D0213')
        r['traces'][0]['标签证据与归属'][0]['confidence']=.5
        self.assertNotIn('VOC-0307',self.ids(j.process(r,self.tax)))


if __name__=='__main__':unittest.main()
