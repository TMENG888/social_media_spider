import unittest
import copy
import test_final_group_reference_protocol_v45 as fixtures
import full_source_key_partition_v53 as v

class SourceKeyPartition(unittest.TestCase):
    def setUp(self):self.entries=[{'source_unit_key':k} for k in 'ABC']
    def test_whole_scheme_may_include_interaction(self):
        self.assertEqual(([(0,2)],[]),v.validate({'groups':[{'start_key':'A','end_key':'C'}]},self.entries))
    def test_no_merge_is_also_valid(self):
        self.assertEqual(([(0,0),(1,1),(2,2)],[]),v.validate({'groups':[{'start_key':k,'end_key':k} for k in 'ABC']},self.entries))
    def test_drop_overlap_unknown_and_extra_fields_rejected(self):
        for g in ([{'start_key':'A','end_key':'B'}],[{'start_key':'B','end_key':'C'}],
                  [{'start_key':'A','end_key':'C'},{'start_key':'C','end_key':'C'}],
                  [{'start_key':['A'],'end_key':'C'}],[{'start_key':'A','end_key':'C','why':'伪理由'}]):
            self.assertTrue(v.validate({'groups':g},self.entries)[1])
    def test_comment_not_processed(self):
        class Runner:
            def call(self,*args,**kwargs):raise AssertionError('comments stay whole')
        plan={'units':[{},{}]}
        self.assertEqual((plan,[],[],[]),v.review({'kind':'评论'},plan,[],Runner()))
    def test_proposal_requires_separate_group_approval_with_literal_program_owned_evidence(self):
        fixture=fixtures.LiteralGroupReferences();fixture.setUp()
        entries=v.ranges.previous.previous.previous.grouping.catalog(fixture.doc,fixture.plan,fixture.segments)
        good=copy.deepcopy(fixture.response['groups'][0])
        good['member_roles']={m['source_unit_key']:m['role'] for m in good.pop('members')}
        good['approved']=True
        good['object_references']=[{'source_unit_key':ref['source_unit_key']} for ref in good['object_references']]
        keys=list(good['member_roles'])
        proposal={'groups':[{'start_key':keys[0],'end_key':keys[-1]},
                            {'start_key':entries[-1]['source_unit_key'],'end_key':entries[-1]['source_unit_key']}]}
        class Runner:
            supports_response_schema=True
            def __init__(self,reject=False):self.requests=[];self.reject=reject
            def call(self,system,payload,doc,phase,**kwargs):
                self.requests.append((payload,kwargs))
                if 'group_members' not in payload:return proposal,{'status':'success'}
                return ({'approved':False,'why':'不同对象'} if self.reject else good),{'status':'success'}
        runner=Runner();out,audit,calls,errors=v.review(fixture.doc,fixture.plan,fixture.segments,runner)
        self.assertFalse(errors);self.assertEqual(2,len(out['units']))
        self.assertEqual(2,len(runner.requests));self.assertIn('response_schema',runner.requests[0][1])
        self.assertEqual(fixture.plan['units'][-1],out['units'][-1])
        rejected=Runner(True);out,audit,calls,errors=v.review(fixture.doc,fixture.plan,fixture.segments,rejected)
        self.assertFalse(errors);self.assertEqual(fixture.plan['units'],out['units'])

if __name__=='__main__':unittest.main()
