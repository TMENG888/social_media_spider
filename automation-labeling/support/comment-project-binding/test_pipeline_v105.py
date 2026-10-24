import copy, unittest
from unittest.mock import patch
import comment_pipeline_v105 as pipeline
from run_additional10 import prepare, CASES


class IntegrationTests(unittest.TestCase):
    def test_new_source_dispatches_old_slicer_then_priority(self):
        source = {'state':'accepted', 'record_id':'test'}
        revised = {'state':'accepted', 'record_id':'test', 'new_project':True}
        args = ({}, [], [], {}, {}, object())
        with patch.object(pipeline.q.p, 'process', return_value=source) as old, \
             patch.object(pipeline, 'process_saved', return_value=(revised, {'passed':True})) as priority:
            actual = pipeline.process_document(*args)
            old.assert_called_once_with(*args)
            priority.assert_called_once_with(source, args[-1])
            self.assertIs(actual[0], revised)

    def test_unfinished_labels_not_exported_as_completed(self):
        with patch.object(pipeline.q.p, 'process', return_value={'state':'retry_required'}) as old, \
             patch.object(pipeline, 'process_saved') as priority:
            self.assertEqual(pipeline.process_document({},[],[],{},{},None), ({'state':'retry_required'},None))
            priority.assert_not_called()

    def test_articles_not_reclassified(self):
        source = {'document':{'kind':'文章'}, 'project':'unchanged'}
        value, proof = pipeline.process_saved(source, None)
        self.assertEqual(value, source); self.assertIsNot(value, source); self.assertIsNone(proof)

    def test_no_successful_labels_no_paid_project_request(self):
        source = {'document':{'kind':'评论'}, 'unfinished_units':[], 'outcomes':{'u':{'views':[]}}}
        with patch.object(pipeline.q, 'resolve') as resolver:
            value, proof = pipeline.process_saved(source, None)
            self.assertEqual(value, source); self.assertIsNone(proof); resolver.assert_not_called()

    def test_new_ten_nonad_and_disjoint(self):
        _, by, plan = prepare()
        self.assertEqual(len(CASES),10)
        self.assertEqual(len({x[0] for x in CASES}),10)
        self.assertEqual(plan['unreviewed_comments_before'],466)
        self.assertTrue(all(x['own_ad_decision']['is_ad']=='否' for x in plan['items']))
        self.assertTrue(all(not by[rid].get('project_attribution_revision') for rid,_ in CASES))

    def test_generic_building_features_cannot_identify_three_projects(self):
        b=[{'fact_id':'F001','decision':'explicit','projects':[
            {'id':'P01','name':'北京臻澐','quote':'品质洋房'},
            {'id':'C02','name':'中海·安澜北京','quote':'品质洋房'},
            {'id':'C05','name':'保利熙瑞','quote':'品质洋房'}]}]
        events=pipeline.q.brand_guard(b,'海淀内城3-5层品质洋房确实舒服')
        self.assertEqual(len(events),1)
        self.assertEqual(b[0]['decision'],'unresolved');self.assertEqual(b[0]['projects'],[])

    def test_no_nicknames_in_first_request_anywhere(self):
        _, by, _ = prepare();s=by['T2-C-1237906']
        payload=pipeline.q.own_payload(s)
        serialized=__import__('json').dumps(payload,ensure_ascii=False)
        self.assertNotIn('蔡欣怡',serialized);self.assertNotIn('父评论｜',serialized)

    def test_cached_ten_use_zero_new_model_calls(self):
        from run_additional10 import OUT
        _, by, _ = prepare();pipeline.configure(OUT)
        class NoRequests:
            def call(self,*args,**kwargs):raise AssertionError('Successful source rerun')
        for rid,_ in CASES:
            revised,proof=pipeline.process_saved(by[rid],NoRequests())
            self.assertTrue(proof['verification']['passed'])
            for outcome in revised['outcomes'].values():
                for view in outcome['views']:
                    for label in view['labels']:
                        if label.get('project_object_field_repair'):
                            self.assertEqual(label['object'],pipeline.q.PM[view['project_id']]['name'])


if __name__ == '__main__': unittest.main()
