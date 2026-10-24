import copy
import unittest
import test_post_split_scope_groups as fixtures
import final_group_protocol_v44 as protocol


class FinalGroupProtocol(unittest.TestCase):
    def setUp(self):
        fixture=fixtures.ScopeGroups();fixture.setUp()
        self.doc=fixture.doc;self.plan=fixture.plan;self.segments=fixture.segments;self.response=fixture.response

    def test_single_member_type_does_not_block_actual_semantic_merge(self):
        self.response['groups'][-1]['kind']='same_object'
        original=copy.deepcopy(self.response)
        out,issues=protocol.apply(self.doc,self.plan,self.segments,self.response)
        self.assertFalse(issues);self.assertEqual(2,len(out['units']))
        self.assertEqual(5,out['units'][1]['source_start_id']);self.assertEqual(original,self.response)
        self.assertEqual(self.plan['units'][4],out['units'][1])

    def test_missing_transition_key_is_identified_not_dropped(self):
        expected=[e['source_unit_key'] for e in protocol.grouping.catalog(self.doc,self.plan,self.segments)]
        missing=self.response['groups'][0]['members'].pop(2)['source_unit_key']
        coverage=protocol.coverage_issues(self.response,expected)
        self.assertEqual([missing],coverage['missing_source_keys'])
        out,issues=protocol.apply(self.doc,self.plan,self.segments,self.response)
        self.assertTrue(issues);self.assertEqual(self.plan,out)

    def test_irrelevant_role_never_auto_changed_to_bridge(self):
        self.response['groups'][0]['members'][2]['role']='irrelevant'
        out,issues=protocol.apply(self.doc,self.plan,self.segments,self.response)
        self.assertTrue(issues);self.assertEqual(self.plan,out)

    def test_multi_object_or_low_confidence_still_rejected(self):
        for field,value in [('same_topic',False),('confidence',.7),('object_scope','project_overview')]:
            candidate=copy.deepcopy(self.response);candidate['groups'][0][field]=value
            self.assertTrue(protocol.apply(self.doc,self.plan,self.segments,candidate)[1])

    def test_retry_receives_actual_missing_key_and_complete_original(self):
        bad=copy.deepcopy(self.response);missing=bad['groups'][0]['members'].pop(2)['source_unit_key']
        fixture=self
        class Runner:
            def __init__(self):self.payloads=[]
            def call(self,system,payload,doc,phase):
                self.payloads.append(payload)
                return copy.deepcopy(bad if len(self.payloads)==1 else fixture.response),{'status':'success'}
        runner=Runner();out,audit,calls,issues=protocol.review(self.doc,self.plan,self.segments,runner)
        self.assertFalse(issues);self.assertEqual(2,len(calls));self.assertEqual(2,len(out['units']))
        self.assertEqual([missing],runner.payloads[1]['missing_source_keys'])
        self.assertEqual(self.doc['text'],runner.payloads[1]['source_text'])


if __name__=='__main__':unittest.main()
