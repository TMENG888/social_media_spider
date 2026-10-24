import copy,unittest
import shared_mechanism_evidence_v57 as v

class SharedMechanismEvidence(unittest.TestCase):
    def setUp(self):
        self.entries=[{'source_unit_key':'A','text':'入口风幕采用门磁联动并配双层密封。'},
                      {'source_unit_key':'B','text':'主持：真棒！'},
                      {'source_unit_key':'C','text':'只加热风不够，仍须门磁联动。'}]
        claim=lambda quote:{'quote':quote,'description':quote}
        self.good={'same_specific_system':True,'later_restates_affirmed_mechanism':True,'has_intervening_independent_object':False,
            'shared_mechanism':{'description':'入口风幕门磁联动','earlier_key':'A','earlier_quote':'门磁联动',
                'later_key':'C','later_quote':'仍须门磁联动'},'object_description':'入口风幕控制','object_scope':'single_solution',
            'object_references':[{'source_unit_key':'A'}],'member_assertions':{
                'A':{'role':'facts','same_specific_system':True,'affirmed_assertions':[claim('入口风幕采用门磁联动并配双层密封')],'rejected_options':[],'confidence':.95},
                'B':{'role':'bridge','same_specific_system':True,'affirmed_assertions':[],'rejected_options':[],'confidence':.95},
                'C':{'role':'facts','same_specific_system':True,'affirmed_assertions':[claim('仍须门磁联动')],'rejected_options':[claim('只加热风不够')],'confidence':.95}},
            'why':'后段重述入口风幕门磁联动；主持情绪未转换物理对象，未新增肯定方案。','confidence':.95}
    def test_partial_restatement_not_all_mechanisms_required(self):
        raw=copy.deepcopy(self.good);out,issues=v.decision(raw,self.entries,self.entries)
        self.assertFalse(issues);self.assertEqual(raw,self.good);self.assertTrue(out['approved'])
    def test_physical_object_or_semantic_rejection_preserved(self):
        for change in ({'same_specific_system':False},{'later_restates_affirmed_mechanism':False},{'has_intervening_independent_object':True}):
            self.assertTrue(v.decision(dict(self.good,**change),self.entries,self.entries)[1])
    def test_exact_member_quotes_required(self):
        raw=copy.deepcopy(self.good);raw['member_assertions']['C']['affirmed_assertions'][0]['quote']='入口采用三层密封'
        self.assertTrue(v.decision(raw,self.entries,self.entries)[1])
    def test_quotes_cannot_borrow_another_member(self):
        raw=copy.deepcopy(self.good);raw['member_assertions']['C']['affirmed_assertions'][0]['quote']='双层密封'
        self.assertTrue(v.decision(raw,self.entries,self.entries)[1])
    def test_rejected_option_cannot_be_shared_affirmed_mechanism(self):
        raw=copy.deepcopy(self.good);raw['shared_mechanism']['later_quote']='只加热风不够'
        self.assertTrue(v.decision(raw,self.entries,self.entries)[1])
    def test_member_coverage_confidence_and_order(self):
        raw=copy.deepcopy(self.good);raw['member_assertions']['B']['confidence']=.89
        self.assertTrue(v.decision(raw,self.entries,self.entries)[1])
        raw=copy.deepcopy(self.good);del raw['member_assertions']['B']
        self.assertTrue(v.decision(raw,self.entries,self.entries)[1])
        raw=copy.deepcopy(self.good);raw['shared_mechanism']['earlier_key']='C'
        self.assertTrue(v.decision(raw,self.entries,self.entries)[1])
    def test_long_internal_reflection_rejected(self):
        raw=copy.deepcopy(self.good);raw['why']='思考过程'*100
        self.assertTrue(v.decision(raw,self.entries,self.entries)[1])
    def test_protocol_bool_and_object_reference(self):
        raw=copy.deepcopy(self.good);raw['same_specific_system']=1
        self.assertTrue(v.decision(raw,self.entries,self.entries)[1])
        raw=copy.deepcopy(self.good);raw['object_references']=[{'source_unit_key':'X'}]
        self.assertTrue(v.decision(raw,self.entries,self.entries)[1])

if __name__=='__main__':unittest.main()
