import unittest
from unittest.mock import patch
import delivery_v59 as v


class IntegratedProtocolTests(unittest.TestCase):
    def test_comment_whole_source_even_model_returns_two_fragments(self):
        text = '主评内容。回复内容。'
        plan, segments, errors = v.comment_partition({'units': [{}, {}]}, text, '评论')
        self.assertEqual(errors, [])
        self.assertEqual(len(plan['units']), 1)
        self.assertEqual(segments[0]['text'], text)
        self.assertEqual(plan['units'][0]['uncertainties'], [])

    def test_comment_protocol_failure_retains_manual_review_row(self):
        doc = {'kind': '评论', 'text': '还在考虑。', 'parent': {}}
        metric = {'status': 'failed'}
        result = ({'exclude': False, 'needs_review': True, 'issues': ['API未成功']}, [metric], [])
        with patch.object(v.scope, 'review', return_value=result), \
             patch.object(v.previous.p.base, 'choose_source', return_value=('', '父文')):
            exclude, unit, audit, actual = v.check_exclusion(doc, {}, [], object())
        self.assertFalse(exclude)
        self.assertFalse(unit['_scope_unresolved'])
        self.assertIn('API未成功', unit['uncertainties'])
        self.assertEqual(actual['status'], 'failed')

    def test_verified_comment_relation_not_removed_by_literal_name_rule(self):
        unit = {'project_ids': ['P1'], '_v59_targets': [{'id': 'P1'}]}
        self.assertEqual(v.detach({'kind': '评论'}, unit, {})['project_ids'], ['P1'])

    def test_comment_mapping_arrays_keep_unknown_candidate_null(self):
        target = {'id': None, 'name': '候选外小区', 'role': '其他'}
        result = {'document': {'kind': '评论'}, 'rows': [{'备注': '', '验收状态': '需人工审核'}],
                  'grounding_response': {'units': [{'_v59_targets': [target]}]}, 'traces': []}
        actual = v.comment_projects(result, {}, object())['rows'][0]
        self.assertEqual(actual['project_id'], [None])
        self.assertEqual(actual['项目名称'], ['候选外小区'])
        self.assertEqual(actual['项目角色'], ['其他'])

    def test_duplicate_projection_removes_label_not_whole_unit(self):
        units = [{'source_start_id': 1, 'source_end_id': 1,
                  'labels': [{'choice_key': 'type'}, {'choice_key': 'area'}]},
                 {'source_start_id': 2, 'source_end_id': 2,
                  'labels': [{'choice_key': 'type'}, {'choice_key': 'balcony'}]}]
        segments = [{'id': 1, 'text': '四居洋房', 'start': 0, 'end': 4},
                    {'id': 2, 'text': '低密洋房', 'start': 4, 'end': 8}]
        decision = {'safe_to_remove': True, 'keep_side': 'A', 'verdict': 'same_fact'}
        with patch.object(v.projection, 'review', return_value=(decision, [], [], [])):
            output, audit, calls = v.duplicate_facts({'kind': '文章', 'text': '四居洋房低密洋房'},
                                                    units, segments, {'type': {}}, object())
        self.assertEqual(len(output), 2)
        self.assertEqual(output[1]['labels'], [{'choice_key': 'balcony'}])
        self.assertEqual(units[1]['labels'][0]['choice_key'], 'type')

    def test_mapping_preserves_inference_and_indices_not_case_text_repairs(self):
        doc = {'kind': '评论', 'row': {'文章id': '9000912876517502726'},
               'parent': {'文章id': '9000912876517502726'}}
        row = {'观点摘要': '主评提出担忧，回复者持不同意见。', '标签明细': [],
               '热度指数': 0, '互动深度指数': None}
        before = dict(row); trace = {}
        v.source_comment_mapping(doc, row, trace, {})
        self.assertEqual(row['映射文章id'], '9000912876517502726')
        for key, value in before.items():
            self.assertEqual(row[key], value)

    def test_mapping_zero_and_missing_stay_distinct(self):
        doc = {'kind': '评论', 'row': {'文章id': 0}, 'parent': {'文章id': None}}
        row = {}; trace = {}
        v.source_comment_mapping(doc, row, trace, {})
        self.assertEqual(row['映射文章id'], '0')
        self.assertIsNone(trace['父文章平台文章id'])


if __name__ == '__main__':
    unittest.main()
