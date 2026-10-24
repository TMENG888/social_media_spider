import unittest
from unittest.mock import patch
import delivery_v75 as v
from prose_speaker_catalog import source_catalog


class ScopeTriageTests(unittest.TestCase):
    def decision(self, text, scope, confidence=.95):
        return {'scope': scope, 'evidence_keys': [source_catalog(text)[0]['source_key']],
                'why': '原文范围核查', 'confidence': confidence}

    def test_empty_tag_is_not_by_itself_an_exclusion(self):
        text = '住宅有明确配置，但字典没有适用路径。'
        self.assertFalse(v.scope_decision(text, self.decision(text, 'product_fact')))

    def test_uncertainty_does_not_delete_a_possible_real_fact(self):
        text = '住宅相关但对象暂不明确。'
        self.assertFalse(v.scope_decision(text, self.decision(text, 'uncertain')))
        self.assertFalse(v.scope_decision(text, self.decision(text, 'unrelated', .89)))

    def test_exclusion_requires_literal_current_slice_evidence(self):
        text = '房企招聘财务岗位，要求英语六级。'
        response = self.decision(text, 'unrelated')
        self.assertTrue(v.scope_decision(text, response))
        response['evidence_keys'] = ['不存在的证据键']
        self.assertFalse(v.scope_decision(text, response))

    def test_removal_preserves_positional_row_trace_alignment(self):
        text = '房企招聘财务岗位。'
        rows = [{'unit_id': 'excluded', '原文摘录': text, '标签明细': [], '备注': ''},
                {'unit_id': 'kept', '原文摘录': '设置泳池', '标签明细': [{'标签路径ID': 'x'}], '备注': ''}]
        result = {'rows': rows, 'traces': [{'unit_id': 'excluded'}, {'unit_id': 'kept'}],
                  'calls': [], 'audit': [], 'complete': True}
        doc = {'topic': v.pipeline.previous.p.base.T1, 'kind': '文章', 'text': text, 'field': '文章内容'}
        response = self.decision(text, 'unrelated')
        with patch.object(v, '_process', return_value=result), patch('bounded_visible_contract_v60.review',
                return_value=(response, [], [], [])):
            actual = v.process_document(doc, [], {}, None)
        self.assertEqual([r['unit_id'] for r in actual['rows']], ['kept'])
        self.assertEqual([r['unit_id'] for r in actual['traces']], ['kept'])
        self.assertEqual(actual['audit'][-1]['排除单元追溯']['unit_id'], 'excluded')
        self.assertTrue(actual['complete'])


if __name__ == '__main__':
    unittest.main()
