import copy
import unittest
import identity_reference_recovery_v45 as protocol


class IdentityRecovery(unittest.TestCase):
    def setUp(self):
        self.parts=['中海甲项目位于甲城。','住宅面积100平方米。','乙项目位于乙城。']
        self.doc={'text':''.join(self.parts)}; self.segments=[]; start=0
        for i,text in enumerate(self.parts,1):
            self.segments.append({'id':i,'text':text,'start':start,'end':start+len(text)});start+=len(text)
        self.units=[{'source_start_id':i,'source_end_id':i} for i in range(1,4)]
        self.entries=protocol.final_catalog.catalog(self.doc,self.units,self.segments)
        self.response={'metadata':[{'unit_index':1,'brand':{'value':'中海','source_keys':[self.entries[1]['source_key']]}}]}

    def test_diagnostic_finds_earlier_literal_name_not_later_context(self):
        original=copy.deepcopy(self.response)
        diagnostic=protocol.diagnostics(self.units,self.segments,self.response,self.entries)
        self.assertEqual([self.entries[0]['source_key']],[r['source_key'] for r in diagnostic[0]['literal_name_references']])
        self.assertEqual(original,self.response)

    def test_future_name_never_offered(self):
        self.response['metadata'][0]['brand']['value']='乙项目'
        diagnostic=protocol.diagnostics(self.units,self.segments,self.response,self.entries)
        self.assertEqual([],diagnostic[0]['literal_name_references'])

    def test_null_keys_explicitly_diagnosed(self):
        self.response['metadata'][0]['brand']['value']=None
        self.assertTrue(protocol.diagnostics(self.units,self.segments,self.response,self.entries))

    def test_valid_literal_keys_no_repair(self):
        self.response['metadata'][0]['brand']['source_keys']=[self.entries[0]['source_key']]
        self.assertEqual([],protocol.diagnostics(self.units,self.segments,self.response,self.entries))


if __name__=='__main__':unittest.main()
