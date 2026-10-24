import copy
import unittest
import test_final_group_reference_protocol_v45 as fixtures
import final_boundary_closure_v50 as closure
import final_range_group_protocol_v50 as ranges


class SourceOnlyIntegration(unittest.TestCase):
    def setUp(self):
        f=fixtures.LiteralGroupReferences();f.setUp()
        self.doc=f.doc;self.plan=f.plan;self.segments=f.segments
        self.group=copy.deepcopy(f.response['groups'][0])
        members=self.group.pop('members')
        self.group['member_roles']={m['source_unit_key']:m['role'] for m in members}
        self.group['approved']=True
        self.keys=list(self.group['member_roles'])

    def test_closure_repairs_actual_bad_object_quote_without_losing_other_ranges(self):
        good=self.group;bad=copy.deepcopy(good)
        bad['object_references'][0]['object_quote']='不存在...的对象'
        keys=self.keys
        class Runner:
            def __init__(self):self.group_calls=0;self.payloads=[]
            def call(self,system,payload,doc,phase):
                self.payloads.append(payload)
                if 'edge_key' in payload:
                    merge=payload['left']['source_unit_key'] in keys and payload['right']['source_unit_key'] in keys
                    return {'edge_key':payload['edge_key'],'decision':'merge' if merge else 'keep',
                        'kind':'same_object','same_topic':merge,'same_object':merge,
                        'left_role':'facts','right_role':'facts','object_description':'同一完整方案',
                        'why':'同对象连续说明' if merge else '不同独立对象','confidence':.95},{'status':'success'}
                self.group_calls+=1
                return (bad if self.group_calls==1 else good),{'status':'success'}
        runner=Runner();out,audit,calls,errors=closure.review(self.doc,self.plan,self.segments,runner)
        self.assertFalse(errors);self.assertEqual(2,len(out['units']))
        self.assertEqual(self.plan['units'][-1],out['units'][-1]);self.assertEqual(2,runner.group_calls)
        self.assertTrue(any(p.get('repair_issues') for p in runner.payloads))
        self.assertEqual('不存在...的对象',bad['object_references'][0]['object_quote'])

    def test_independent_range_rejection_keeps_source_partition(self):
        group=dict(self.group,start_key=self.keys[0],end_key=self.keys[-1])
        entries=ranges.previous.previous.previous.grouping.catalog(self.doc,self.plan,self.segments)
        proposal={'groups':[group,{'start_key':entries[-1]['source_unit_key'],
            'end_key':entries[-1]['source_unit_key'],'kind':'singleton'}]}
        class Runner:
            def call(self,system,payload,doc,phase):
                return ({'approved':False,'why':'跨独立主题','confidence':.95}
                    if 'group_members' in payload else proposal),{'status':'success'}
        out,audit,calls,errors=ranges.review(self.doc,self.plan,self.segments,Runner())
        self.assertFalse(errors);self.assertEqual(self.plan['units'],out['units'])

    def test_comments_are_not_sliced(self):
        class Runner:
            def call(self,*args):raise AssertionError('No article boundary logic on comments')
        for module in (ranges,closure):
            self.assertEqual(self.plan,module.review(dict(self.doc,kind='评论'),self.plan,self.segments,Runner())[0])


if __name__=='__main__':unittest.main()
