import unittest
import delivery_v11 as pipeline


class ProseRunner:
    def __init__(self):self.requests=[]
    def call(self,system,payload,doc,phase):
        self.requests.append((system,payload,phase))
        metrics={'status':'success'}
        if 'prose_catalog' in payload:
            key=payload['source_evidence_catalog'][0]['source_key']
            response={'checks':[{'prose_key':e['prose_key'],'status':'supported',
                    'source_keys':[key],'why':'原文规划架桥陈述','confidence':.95,
                    'assertion_quote':e['text'],
                    'object_binding_supported':True,'relation_supported':True,
                    'modality_preserved':True,'qualifiers_preserved':True,
                    'object_bindings':[{'assertion_quote':e['text'],'object_quote':None,
                        'object_source_key':None,'attribute_source_key':key,
                        'attribute_quote':payload['source_evidence_catalog'][0]['text'],
                        'generic_or_unresolved':True}]}
                    for e in payload['prose_catalog']],
                    'coverage':{'captures_primary_points':True,'source_keys':[key],
                                'why':'核心规划事实保留','confidence':.95}}
            if '禁止另造assertion_quote' in system:
                check=response['checks'][0];check.pop('assertion_quote')
                response['object_bindings']=check.pop('object_bindings')
                for binding in response['object_bindings']:
                    binding.pop('assertion_quote');binding['prose_key']=check['prose_key']
            if '禁止返回attribute_quote或assertion_quote' in system:
                check=response['checks'][0];check.pop('assertion_quote')
                response['object_bindings']=check.pop('object_bindings')
                for binding in response['object_bindings']:
                    binding.pop('assertion_quote');binding.pop('attribute_quote')
                    binding.pop('generic_or_unresolved')
                    binding['prose_key']=check['prose_key']
            return response,metrics
        if 'previous_prose' in payload:
            return {'summary':'回复者称项目规划在永引渠上架桥。','supported':True,'confidence':.95},metrics
        raise AssertionError('Unexpected stage '+phase)


class ProductionProseIntegration(unittest.TestCase):
    def test_role_guard_rejects_supported_looking_profession_then_reaudits_rewrite(self):
        source='【子评论1｜北京安信房产置业丨盛丰】您好，项目规划在永引渠上架一座桥。'
        runner=ProseRunner()
        out,audit,calls,issues=pipeline.independent_prose_review(
            {'topic':'北京臻澐项目口碑','kind':'评论'},
            {'summary':'置业顾问称项目规划在永引渠上架桥。','labels':[]},source,'',runner)
        self.assertFalse(issues)
        self.assertEqual('回复者称项目规划在永引渠上架桥。',out['summary'])
        self.assertEqual(4,len(calls))
        self.assertFalse(audit[0]['passed']);self.assertTrue(audit[-1]['passed'])
        self.assertIn('speaker',runner.requests[0][1]['source_evidence_catalog'][0])
        self.assertIn('source_evidence_catalog',runner.requests[1][1])
    def test_production_signature_covers_all_new_behavior_modules(self):
        expected={'prose_audit_references.py','prose_speaker_catalog.py','prose_role_evidence.py',
                  'customer_configuration_reason.py','duplicate_precision_scope.py','continuity_edge_references.py',
                  'comment_object_bindings.py'}
        self.assertTrue(expected<=set(pipeline.IMPLEMENTATION_FILES))
        expected|={'article_identity_review_protocol.py','post_split_scope_groups.py',
                   'comment_single_target_binding_protocol.py','comment_explicit_name_coverage.py',
                   'branch_added_condition_review.py','definition_alternative_conditions.py','asr_scope_fidelity.py'}
        self.assertTrue(expected<=set(pipeline.IMPLEMENTATION_FILES))
        expected|={'final_interval_source_catalog.py','literal_comment_name_key_protocol.py','comment_binding_schema_v44.py',
                   'final_group_protocol_v44.py','relative_comparison_guard.py'}
        self.assertTrue(expected<=set(pipeline.IMPLEMENTATION_FILES))
        expected|={'relative_comparison_guard_v45.py','identity_reference_recovery_v45.py','final_group_reference_protocol_v45.py'}
        self.assertTrue(expected<=set(pipeline.IMPLEMENTATION_FILES))
        expected|={'final_range_group_protocol_v46.py','clear_asr_fact_prose_recovery.py'}
        self.assertTrue(expected<=set(pipeline.IMPLEMENTATION_FILES))
        expected|={'comment_key_only_attribute_protocol_v47.py','final_boundary_closure_v47.py'}
        self.assertTrue(expected<=set(pipeline.IMPLEMENTATION_FILES))
        expected|={'complete_solution_fewshots_v52.py','semantic_subgroups_v52.py'}
        expected|={'full_source_key_partition_v53.py','source_claim_category_v53.py'}
        expected|={'source_object_fact_ledger_v54.py','full_source_inventory_partition_v54.py'}
        expected|={'inventory_continuity_candidates_v55.py','article_local_alias_review_v55.py'}
        expected|={'affirmed_mechanism_proof_v56.py','local_alias_check_schema_v56.py'}
        expected|={'shared_mechanism_evidence_v57.py','physical_scope_pass_v57.py','comment_qualification_feedback_v57.py'}
        self.assertTrue(expected<=set(pipeline.IMPLEMENTATION_FILES))
        expected|={'shared_mechanism_protocol_v58.py','physical_scope_object_protocol_v58.py',
                   'structured_response_validation_v58.py','comment_attribution_feedback_v58.py'}
        self.assertTrue(expected<=set(pipeline.IMPLEMENTATION_FILES))
        self.assertIn('v11.58',pipeline.VERSION)
        import physical_scope_object_protocol_v58,comment_attribution_feedback_v58
        import inventory_continuity_candidates_v55,shared_mechanism_protocol_v58
        self.assertIs(pipeline.physical_scopes,physical_scope_object_protocol_v58)
        self.assertIs(pipeline.qualification_feedback,comment_attribution_feedback_v58)
        self.assertIs(inventory_continuity_candidates_v55.mechanism_proof,shared_mechanism_protocol_v58)


if __name__=='__main__':unittest.main()
