import copy
import unittest
import test_final_group_reference_protocol_v45 as fixtures
import final_range_group_protocol_v46 as protocol


class ConsecutiveGroupRanges(unittest.TestCase):
    def setUp(self):
        f=fixtures.LiteralGroupReferences();f.setUp()
        self.doc=f.doc;self.plan=f.plan;self.segments=f.segments
        self.response=copy.deepcopy(f.response)
        for g in self.response['groups']:
            members=g.pop('members');g['start_key']=members[0]['source_unit_key'];g['end_key']=members[-1]['source_unit_key']
            g['member_roles']={m['source_unit_key']:m['role'] for m in members}
            if len(members)==1:
                for k in list(g):
                    if k not in ('start_key','end_key','kind'):del g[k]

    def test_valid_ranges_keep_all_text_and_merge_complete_scheme(self):
        original=copy.deepcopy(self.response)
        out,errors=protocol.apply(self.doc,self.plan,self.segments,self.response)
        self.assertFalse(errors);self.assertEqual(2,len(out['units']))
        self.assertEqual(original,self.response)
        self.assertEqual(self.plan['units'][-1],out['units'][-1])

    def test_gap_or_overlap_not_reordered(self):
        for key in ('start_key','end_key'):
            r=copy.deepcopy(self.response);r['groups'][1][key]=r['groups'][0][key]
            self.assertTrue(protocol.apply(self.doc,self.plan,self.segments,r)[1])

    def test_cannot_skip_bridge_inside_range(self):
        self.response['groups'][0]['member_roles'].pop(next(iter(self.response['groups'][0]['member_roles'])))
        self.assertTrue(protocol.apply(self.doc,self.plan,self.segments,self.response)[1])

    def test_missing_merge_confidence_still_rejected(self):
        self.response['groups'][0].pop('confidence')
        self.assertTrue(protocol.apply(self.doc,self.plan,self.segments,self.response)[1])

    def test_unknown_key_or_general_object_rejected(self):
        for key,value in [('start_key','FAKE'),('object_scope','project_overview')]:
            r=copy.deepcopy(self.response);r['groups'][0][key]=value
            self.assertTrue(protocol.apply(self.doc,self.plan,self.segments,r)[1])

    def test_comments_bypass_without_any_model_call(self):
        class Runner:
            def call(self,*args):raise AssertionError('Comment must not be grouped')
        doc=dict(self.doc,kind='评论')
        self.assertEqual(self.plan,protocol.review(doc,self.plan,self.segments,Runner())[0])

    def test_catalog_does_not_feed_prior_generated_object_reasons(self):
        entries=protocol.previous.previous.grouping.catalog(self.doc,self.plan,self.segments)
        self.assertTrue(all(set(e)=={'source_unit_key','text','start','end'} for e in entries))

    def test_independent_range_rejection_does_not_coarsen_source(self):
        response=self.response
        class Runner:
            def call(self,system,payload,doc,phase):
                if 'group_members' in payload:
                    return {'approved':False,'why':'不同独立主题','confidence':.95},{'status':'success'}
                return response,{'status':'success'}
        out,audit,calls,errors=protocol.review(self.doc,self.plan,self.segments,Runner())
        self.assertFalse(errors);self.assertEqual(self.plan['units'],out['units'])
        self.assertTrue(any('independent_range' in a for a in audit))

    def test_independent_valid_complete_scheme_is_applied(self):
        response=self.response
        verified=dict(response['groups'][0],approved=True)
        class Runner:
            def call(self,system,payload,doc,phase):
                return (verified if 'group_members' in payload else response),{'status':'success'}
        out,audit,calls,errors=protocol.review(self.doc,self.plan,self.segments,Runner())
        self.assertFalse(errors);self.assertEqual(2,len(out['units']))
        self.assertTrue(any(a.get('accepted') is True for a in audit))

    def test_high_confidence_invalid_independent_object_scope_is_not_applied(self):
        response=self.response
        verified=dict(response['groups'][0],approved=True,object_scope='project_overview',confidence=.99)
        class Runner:
            def call(self,system,payload,doc,phase):
                return (verified if 'group_members' in payload else response),{'status':'success'}
        out,audit,calls,errors=protocol.review(self.doc,self.plan,self.segments,Runner())
        self.assertFalse(errors);self.assertEqual(self.plan['units'],out['units'])
        self.assertTrue(any(a.get('issues') for a in audit))


if __name__=='__main__':unittest.main()
