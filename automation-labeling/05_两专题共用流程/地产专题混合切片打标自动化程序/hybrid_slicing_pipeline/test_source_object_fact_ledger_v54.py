import copy,unittest
import source_object_fact_ledger_v54 as v

class LiteralLedger(unittest.TestCase):
    def setUp(self):
        self.entries=[{'source_unit_key':'A','text':'入口风幕门控方案'},
                      {'source_unit_key':'B','text':'仍须入口门控而非仅加热'}]
        self.record={'object_description':'入口风幕系统','fact_description':'说明门控',
                     'object_reference_keys':['A'],'related_source_keys':[],
                     'relation':'new_object','confidence':.95}
        self.good={'members':{'A':copy.deepcopy(self.record),'B':dict(self.record,related_source_keys=['A'],relation='correction')}}
    def test_source_owned_evidence_and_no_response_rewrite(self):
        original=copy.deepcopy(self.good);ledger,issues=v.materialize(self.good,self.entries)
        self.assertFalse(issues);self.assertEqual(original,self.good)
        self.assertEqual('入口风幕门控方案',ledger['members']['B']['object_reference_keys_sources'][0]['text'])
    def test_unknown_nested_future_and_self_keys_rejected(self):
        for field,refs,key in [('object_reference_keys',['X'],'B'),('object_reference_keys',[['A']],'B'),
                               ('related_source_keys',['B'],'A'),('related_source_keys',['B'],'B')]:
            r=copy.deepcopy(self.good);r['members'][key][field]=refs
            self.assertTrue(v.materialize(r,self.entries)[1])
    def test_missing_member_and_model_quote_rejected(self):
        r=copy.deepcopy(self.good);del r['members']['B'];self.assertTrue(v.materialize(r,self.entries)[1])
        r=copy.deepcopy(self.good);r['members']['B']['object_quote']='假引文'
        self.assertTrue(v.materialize(r,self.entries)[1])
    def test_low_confidence_preserved_not_promoted(self):
        self.good['members']['B']['confidence']=.4
        out,issues=v.materialize(self.good,self.entries)
        self.assertFalse(issues);self.assertEqual(.4,out['members']['B']['confidence'])
    def test_new_object_not_auto_merged(self):
        out,issues=v.materialize(self.good,self.entries)
        self.assertFalse(issues);self.assertNotIn('groups',out)
    def test_later_literal_object_context_can_be_considered_but_not_prior_relation(self):
        self.good['members']['A']['object_reference_keys']=['B']
        out,issues=v.materialize(self.good,self.entries)
        self.assertFalse(issues);self.assertEqual('B',out['members']['A']['object_reference_keys'][0])

if __name__=='__main__':unittest.main()
