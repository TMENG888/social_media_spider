"""Offline contract tests only: mocked Qwen calls, no paid requests."""
import unittest
from unittest.mock import patch
import repair_failed as recovery
batch=recovery.batch

class RecoveryTests(unittest.TestCase):
    def test_summary_evidence_ids_are_local_enum(self):
        payload={'unit_text':'客厅宽敞。','claims':[{'id':1,'text':'客厅宽敞。'}],'evidence_grid':[{'id':1,'start':0,'end':6,'text':'客厅宽敞。'}],'level':'I0 无创新判断'}
        draft={'checks':[{'claim_id':1,'supported':True,'evidence_ids':[999],'reason':'依据'}],'innovation_supported':True,'innovation_issue':''}
        repaired={**draft,'checks':[{**draft['checks'][0],'evidence_ids':[1]}]}
        result,call=self.run_case('专题一摘要编号核验合同修复',payload,draft,repaired)
        self.assertEqual(result,repaired)
        schema=call.call_args.kwargs['response_schema']
        self.assertEqual(schema['properties']['checks']['items']['properties']['evidence_ids']['items']['enum'],[1])

    def run_case(self,phase,payload,draft,repaired,expected_calls=2):
        runner=recovery.RepairRunner.__new__(recovery.RepairRunner)
        metrics={'status':'success','request_key':'offline-test'}
        with patch.object(batch.Runner,'call',side_effect=[(draft,metrics),(repaired,metrics)]) as call,patch.object(batch,'save'):
            result,_=runner.call('original semantic rules',payload,{'record_id':'offline-test'},phase)
        self.assertEqual(call.call_count,expected_calls)
        return result,call

    def test_invalid_identity_ids_get_enum_schema(self):
        draft={f:{'value':'','evidence_ids':[999]} for f in ['brand','entity','city','publisher_role']}
        repaired={f:{'value':'','evidence_ids':[]} for f in draft}
        repaired['publisher_role']['value']='身份不明'
        payload={'evidence_grid':[{'id':1,'quote':'source'}],'allowed_entities':{'中国金茂':'金茂'}}
        result,call=self.run_case('专题一身份编号合同修复',payload,draft,repaired)
        self.assertEqual(result,repaired)
        schema=call.call_args.kwargs['response_schema']
        self.assertEqual(schema['properties']['brand']['properties']['evidence_ids']['items']['enum'],[1])

    def test_valid_identity_response_is_unchanged(self):
        draft={f:{'value':'','evidence_ids':[]} for f in ['brand','entity','city','publisher_role']}
        draft['publisher_role']['value']='身份不明'
        result,_=self.run_case('专题一身份编号合同修复',{'evidence_grid':[{'id':1}],'allowed_entities':{}},draft,None,1)
        self.assertEqual(result,draft)

    def test_local_summary_enum_schema_preserves_frozen_options(self):
        result,call=self.run_case('专题一当前切片摘要合同修复',{'unit_text':'原文产品'}, {'deliver':True,'innovation':'other','level':'I0'}, {'deliver':True,'practice':'原文产品'})
        self.assertEqual(result,{'deliver':True,'practice':'原文产品'})
        schema=call.call_args.kwargs['response_schema']
        self.assertEqual(schema['properties']['innovation']['enum'],batch.pipeline.INNOVATIONS)
        self.assertEqual(schema['properties']['level']['enum'],batch.pipeline.LEVELS)

    def test_annotation_requires_all_source_indices(self):
        _,call=self.run_case('专题一字段独立生成',{'units':[{'index':1},{'index':2}]},{'units':[]},{'units':[]})
        schema=call.call_args.kwargs['response_schema']['properties']['units']
        self.assertEqual((schema['minItems'],schema['maxItems']),(2,2))
        self.assertEqual(schema['items']['properties']['index']['enum'],[1,2])

    def test_verified_product_preserves_existing_force_product_rule(self):
        draft={'deliver':False,'innovation':batch.pipeline.INNOVATIONS[-1],'level':batch.pipeline.LEVELS[0],'practice':''}
        _,call=self.run_case('专题一当前切片摘要合同修复',{'unit_text':'原文产品','verified_current_unit_labels':[{'tag_id':'example'}]},draft,{'deliver':True,'practice':'原文产品'})
        self.assertEqual(call.call_args.kwargs['response_schema']['properties']['deliver']['enum'],[True])

    def test_empty_repaired_summary_gets_bounded_nonempty_recovery(self):
        runner=recovery.RepairRunner.__new__(recovery.RepairRunner)
        metrics={'status':'success','request_key':'offline-test'}
        draft={'deliver':False,'innovation':'bad','level':'bad'}
        empty={'deliver':True,'practice':''}
        fixed={'deliver':True,'practice':'原文产品'}
        with patch.object(batch.Runner,'call',side_effect=[(draft,metrics),(empty,metrics),(fixed,metrics)]) as call,patch.object(batch,'save'):
            result,_=runner.call('rules',{'unit_text':'原文产品','verified_current_unit_labels':[{}]},{'record_id':'test'},'专题一当前切片摘要合同修复')
        self.assertEqual(result,fixed)
        self.assertEqual(call.call_count,3)
        self.assertEqual(call.call_args.kwargs['response_schema']['properties']['practice']['minLength'],1)

    def test_local_first_point_is_selected_by_qwen(self):
        text='abc def ghi'
        result,_=self.run_case('专题一局部切片合同修复',{'text':text},{'cuts':[{'quote':'def ghi','occurrence':1,'theme':'second'}]},
            {'cuts':[{'anchor_id':0,'theme':'first'},{'anchor_id':4,'theme':'second'}]})
        parts=batch.pipeline.resolve_cuts({'text':text},result)
        self.assertEqual([p['start'] for p in parts],[0,4])
        self.assertEqual(''.join(p['text'] for p in parts),text)
        self.assertIsNotNone(parts[0]['anchor_audit']['model_quote'])

if __name__=='__main__':unittest.main()
