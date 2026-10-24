import copy
import unittest
import test_post_split_scope_groups as fixtures
import final_group_reference_protocol_v45 as protocol


class LiteralGroupReferences(unittest.TestCase):
    def setUp(self):
        f=fixtures.ScopeGroups();f.setUp()
        self.doc=f.doc;self.plan=f.plan;self.segments=f.segments;self.response=copy.deepcopy(f.response)
        entries=protocol.previous.grouping.catalog(self.doc,self.plan,self.segments)
        for group in self.response['groups']:
            if len(group['members'])>1:
                quote=group.pop('object_source_quotes')[0]
                entry=next(e for e in entries if quote in e['text'])
                group['object_references']=[{'source_unit_key':entry['source_unit_key'],'object_quote':quote}]

    def test_model_group_grounded_by_literal_key(self):
        original=copy.deepcopy(self.response)
        out,errors=protocol.apply(self.doc,self.plan,self.segments,self.response)
        self.assertFalse(errors);self.assertEqual(2,len(out['units']))
        self.assertEqual(original,self.response)

    def test_fabricated_quote_rejected_not_repaired(self):
        self.response['groups'][0]['object_references'][0]['object_quote']='卫生间...方案'
        out,errors=protocol.apply(self.doc,self.plan,self.segments,self.response)
        self.assertTrue(errors);self.assertEqual(self.plan,out)

    def test_unknown_key_rejected(self):
        self.response['groups'][0]['object_references'][0]['source_unit_key']='UNKNOWN'
        self.assertTrue(protocol.apply(self.doc,self.plan,self.segments,self.response)[1])

    def test_legacy_quotes_do_not_silently_pass(self):
        self.response['groups'][0].pop('object_references')
        self.assertTrue(protocol.apply(self.doc,self.plan,self.segments,self.response)[1])

    def test_wrong_scope_and_dropped_member_still_rejected(self):
        for change in ('scope','member'):
            response=copy.deepcopy(self.response)
            if change=='scope':response['groups'][0]['object_scope']='project_overview'
            else:response['groups'][0]['members'].pop(1)
            self.assertTrue(protocol.apply(self.doc,self.plan,self.segments,response)[1])


if __name__=='__main__':unittest.main()
