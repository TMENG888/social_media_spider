import unittest
import copy
import test_final_group_reference_protocol_v45 as fixtures
import final_boundary_closure_v47 as closing


class BoundaryClosure(unittest.TestCase):
    def setUp(self):
        self.response={'edge_key':'K','decision':'merge','kind':'same_object','same_topic':True,'same_object':True,
            'left_role':'object_frame','right_role':'facts','object_description':'大堂分区温控完整方案',
            'why':'具体对象引导紧接方案回答，没有切换对象','confidence':.95}

    def test_semantic_frame_facts_can_merge(self):
        self.assertIsNotNone(closing.edge_decision(self.response,'K'))

    def test_unrelated_role_cannot_merge(self):
        self.response['left_role']='irrelevant'
        self.assertIsNone(closing.edge_decision(self.response,'K'))

    def test_low_confidence_wrong_key_or_different_object_rejected(self):
        for key,value in [('confidence',.89),('edge_key','WRONG'),('same_object',False)]:
            d=dict(self.response);d[key]=value
            self.assertIsNone(closing.edge_decision(d,'K'))

    def test_uncertain_boundary_never_guessed(self):
        self.response['decision']='uncertain'
        self.assertIsNone(closing.edge_decision(self.response,'K'))
        self.assertEqual([(0,0),(1,2)],closing.chains({1:{'decision':'merge'}},3))

    def test_comparison_only_for_topic_two(self):
        self.response.update(kind='comparison',same_object=False)
        self.assertIsNotNone(closing.edge_decision(self.response,'K','北京臻澐项目口碑'))
        self.assertIsNone(closing.edge_decision(self.response,'K','全国地产设计产品力监测'))

    def test_complete_adjacent_chain_keeps_other_topic_separate(self):
        self.assertEqual([(0,3),(4,4)],closing.chains({i:{'decision':'merge'} for i in range(3)},5))

    def test_comments_never_sliced_or_model_called(self):
        class Runner:
            def call(self,*args):raise AssertionError('Comment is not an article boundary')
        plan={'units':[{},{}]}
        self.assertEqual((plan,[],[],[]),closing.review({'kind':'评论'},plan,[],Runner()))

    def test_real_review_wiring_requires_independent_whole_chain(self):
        fixture=fixtures.LiteralGroupReferences();fixture.setUp()
        group=copy.deepcopy(fixture.response['groups'][0]);group['approved']=True
        roles={m['source_unit_key']:m['role'] for m in group.pop('members')};group['member_roles']=roles
        class Runner:
            def __init__(self):self.payloads=[]
            def call(self,system,payload,doc,phase):
                self.payloads.append(payload)
                if 'edge_key' in payload:
                    merge=payload['left']['source_unit_key'] in roles and payload['right']['source_unit_key'] in roles
                    return {'edge_key':payload['edge_key'],'decision':'merge' if merge else 'keep','kind':'same_object',
                        'same_topic':merge,'same_object':merge,'left_role':roles.get(payload['left']['source_unit_key'],'facts'),
                        'right_role':roles.get(payload['right']['source_unit_key'],'facts'),
                        'object_description':'同一个完整方案' if merge else '独立厨房主题',
                        'why':'对象引导及连续解释共同构成完整方案' if merge else '下一厨房主题独立','confidence':.95},{'status':'success'}
                return group,{'status':'success'}
        runner=Runner()
        out,audit,calls,errors=closing.review(fixture.doc,fixture.plan,fixture.segments,runner)
        self.assertFalse(errors);self.assertEqual(2,len(out['units']))
        self.assertEqual(fixture.plan['units'][-1],out['units'][-1])
        self.assertEqual(4,len(next(p['group_members'] for p in runner.payloads if 'group_members' in p)))
        self.assertTrue(all(p['source_text']==fixture.doc['text'] for p in runner.payloads))


if __name__=='__main__':unittest.main()
