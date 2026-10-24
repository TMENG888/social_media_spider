import unittest
from article_identity_references import catalog,apply


class IdentityReferences(unittest.TestCase):
    def setUp(self):
        self.source='甲项目。该项目会所。乙项目交通。'
        self.entries=catalog(self.source,['甲项目','乙项目'])
        self.units=[{'source_end_id':1},{'source_end_id':2},{'source_end_id':3}]
        self.segments=[{'end':4},{'end':10},{'end':len(self.source)}]
        self.response={'contexts':[{'unit_index':i,'assigned':True,'identity_key':self.entries[0]['source_key'],
                                    'why':'连续承接','confidence':.95} for i in range(3)]}
    def test_literal_key_replaces_occurrence_count(self):
        out,issues=apply(self.units,self.segments,self.response,self.entries)
        self.assertFalse(issues);self.assertEqual('甲项目',out[1]['object_quote'])
        self.assertNotIn('object_quote',self.units[1])
    def test_future_identity_does_not_apply_to_earlier_slice(self):
        self.response['contexts'][0]['identity_key']=self.entries[1]['source_key']
        out,issues=apply(self.units,self.segments,self.response,self.entries)
        self.assertTrue(issues);self.assertIsNone(out[0]['object_quote']);self.assertEqual('甲项目',out[1]['object_quote'])
    def test_source_key_not_unit_ordinal_or_invented_quote(self):
        for key in (1,'IDENT-0001','甲项目...乙项目'):
            self.response['contexts'][0]['identity_key']=key
            self.assertTrue(apply(self.units,self.segments,self.response,self.entries)[1])
    def test_repeated_index_protocol_failure_not_guessed(self):
        self.response['contexts'][2]['unit_index']=1
        self.assertTrue(apply(self.units,self.segments,self.response,self.entries)[1])
    def test_repeated_names_have_distinct_literal_keys(self):
        entries=catalog('甲项目。甲项目。',['甲项目'])
        self.assertNotEqual(entries[0]['source_key'],entries[1]['source_key'])
    def test_negative_or_missing_review_clears_initial_unverified_context(self):
        self.units[0]['object_quote']='乙项目'
        self.response['contexts'][0]={'unit_index':0,'assigned':False,'identity_key':None,'why':'归属未明'}
        self.assertIsNone(apply(self.units,self.segments,self.response,self.entries)[0][0]['object_quote'])
        self.assertIsNone(apply(self.units,self.segments,{},self.entries)[0][0]['object_quote'])


if __name__=='__main__':unittest.main()
