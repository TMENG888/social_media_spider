import copy
import unittest
import source_only_group_recovery_v50 as protocol


class BoundedGroupRecovery(unittest.TestCase):
    def setUp(self):
        self.doc={'text':'卫生间采用存水弯。配置自动补水。','topic':'全国地产设计产品力监测'}
        self.entries=[{'source_unit_key':'A','text':'卫生间采用存水弯。'},
                      {'source_unit_key':'B','text':'配置自动补水。'}]
        self.good={'approved':True,'kind':'same_object','confidence':.95,
            'object_references':[{'source_unit_key':'A','object_quote':'卫生间'}]}

    def test_actual_repair_not_silent_quote_replacement(self):
        bad=copy.deepcopy(self.good);bad['object_references'][0]['object_quote']='卫生间...自动补水'
        initial=copy.deepcopy(bad);good=self.good
        class Runner:
            def __init__(self):self.payloads=[]
            def call(self,system,payload,doc,phase):
                self.payloads.append(payload);return good,{'status':'success'}
        def validate(r):
            return [] if r['object_references'][0]['object_quote']=='卫生间' else ['伪引文']
        runner=Runner();out,audit,calls,issues=protocol.review(self.doc,self.entries,0,1,runner,'S',validate,(bad,{'status':'success'}))
        self.assertEqual(initial,bad);self.assertEqual(self.good,out);self.assertFalse(issues)
        self.assertEqual(1,len(calls));self.assertEqual(initial,runner.payloads[0]['previous_response'])
        self.assertFalse(audit[0]['accepted']);self.assertTrue(audit[1]['accepted'])

    def test_semantic_rejection_is_not_retried_for_agreement(self):
        class Runner:
            def call(self,*args):raise AssertionError('Do not retry explicit semantic rejection')
        out,audit,calls,issues=protocol.review(self.doc,self.entries,0,1,Runner(),'S',lambda r:[],
            ({'approved':False,'why':'不同对象','confidence':.95},{'status':'success'}))
        self.assertIsNone(out);self.assertTrue(issues);self.assertFalse(calls)

    def test_multi_axis_comparison_never_passes_as_single_topic(self):
        r={'kind':'comparison','comparison_axis':'floorplan','member_roles':{'A':'facts','B':'facts'},
           'member_axes':{'A':['floorplan'],'B':['finishing']}}
        self.assertTrue(protocol.comparison_issues(r,self.entries))
        r['member_axes']['B']=['floorplan','finishing']
        self.assertTrue(protocol.comparison_issues(r,self.entries))

    def test_same_floorplan_parameters_and_explanation_can_share_axis(self):
        r={'kind':'comparison','comparison_axis':'floorplan','member_roles':{'A':'facts','B':'facts'},
           'member_axes':{'A':['floorplan'],'B':['floorplan']}}
        self.assertFalse(protocol.comparison_issues(r,self.entries))

    def test_project_comparison_is_not_a_valid_axis(self):
        r={'kind':'comparison','comparison_axis':'project_comparison','member_roles':{'A':'facts','B':'facts'},
           'member_axes':{'A':['project_comparison'],'B':['project_comparison']}}
        self.assertTrue(protocol.comparison_issues(r,self.entries))

    def test_nested_axis_json_is_rejected_without_crashing(self):
        r={'kind':'comparison','comparison_axis':['floorplan'],'member_roles':{'A':'facts','B':'facts'},
           'member_axes':{'A':['floorplan'],'B':['floorplan']}}
        self.assertTrue(protocol.comparison_issues(r,self.entries))
        r['comparison_axis']='floorplan';r['member_axes']['B']=[['finishing']]
        self.assertTrue(protocol.comparison_issues(r,self.entries))

    def test_ongoing_format_failure_has_bounded_calls_and_no_output(self):
        bad=dict(self.good,confidence=.89)
        class Runner:
            def __init__(self):self.calls=0
            def call(self,*args):self.calls+=1;return bad,{'status':'success'}
        runner=Runner();out,audit,calls,issues=protocol.review(self.doc,self.entries,0,1,runner,'S',lambda r:[])
        self.assertIsNone(out);self.assertEqual(2,runner.calls);self.assertTrue(issues)


if __name__=='__main__':unittest.main()
