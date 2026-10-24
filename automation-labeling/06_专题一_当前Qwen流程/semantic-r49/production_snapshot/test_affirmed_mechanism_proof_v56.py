import copy,unittest
import affirmed_mechanism_proof_v56 as v
import test_final_group_reference_protocol_v45 as fixtures
import final_range_group_protocol_v50 as ranges
import source_only_group_recovery_v50 as recovery

class AffirmedMechanism(unittest.TestCase):
    def setUp(self):
        self.entries=[{'source_unit_key':'A','text':'入口采用门磁联动风幕。'},
                      {'source_unit_key':'B','text':'主持附和。'},
                      {'source_unit_key':'C','text':'仅加热风不够，仍须门磁联动。'}]
        r=lambda role,facts,rejected=[]:{'role':role,'same_specific_system':True,'affirmed_assertions':facts,
                                       'rejected_options':rejected,'confidence':.95}
        self.good={'same_specific_system':True,'later_restates_affirmed_mechanism':True,'has_intervening_independent_object':False,
            'shared_affirmed_mechanism':'入口门磁联动风幕','object_description':'入口风幕控制','object_scope':'single_solution',
            'object_references':[{'source_unit_key':'A'}],'member_assertions':{'A':r('facts',['门磁联动风幕']),
                'B':r('bridge',[]),'C':r('facts',['仍须门磁联动'],['仅加热風'])},'why':'同一肯定机制的纠正说明，未换系统','confidence':.95}
    def test_rejected_option_not_a_second_affirmed_solution(self):
        raw=copy.deepcopy(self.good);out,issues=v.decision(raw,self.entries,self.entries)
        self.assertFalse(issues);self.assertTrue(out['approved']);self.assertEqual(self.good,raw)
        self.assertEqual('入口采用门磁联动风幕。',out['object_references'][0]['object_quote'])
    def test_other_system_or_no_restatement_blocks(self):
        for change in ({'same_specific_system':False},{'later_restates_affirmed_mechanism':False},
                       {'has_intervening_independent_object':True},{'confidence':.89}):
            self.assertTrue(v.decision(dict(self.good,**change),self.entries,self.entries)[1])
    def test_each_member_and_actual_reference_required(self):
        raw=copy.deepcopy(self.good);raw['member_assertions']['B']['same_specific_system']=False
        self.assertTrue(v.decision(raw,self.entries,self.entries)[1])
        raw=copy.deepcopy(self.good);raw['object_references']=[{'source_unit_key':'X'}]
        self.assertTrue(v.decision(raw,self.entries,self.entries)[1])
        raw=copy.deepcopy(self.good);del raw['member_assertions']['B']
        self.assertTrue(v.decision(raw,self.entries,self.entries)[1])
    def test_negated_options_alone_not_positive_facts(self):
        raw=copy.deepcopy(self.good);raw['member_assertions']['C']['affirmed_assertions']=[]
        self.assertTrue(v.decision(raw,self.entries,self.entries)[1])
    def test_extra_or_missing_fields_not_silently_accepted(self):
        raw=copy.deepcopy(self.good);raw['force_merge']=True
        self.assertTrue(v.decision(raw,self.entries,self.entries)[1])
    def test_actual_group_apply_checks_literal_whole_partition(self):
        f=fixtures.LiteralGroupReferences();f.setUp()
        entries=ranges.previous.previous.previous.grouping.catalog(f.doc,f.plan,f.segments)
        group=f.response['groups'][0];members=group['members'];keys={m['source_unit_key'] for m in members}
        selected=[e for e in entries if e['source_unit_key'] in keys]
        raw=copy.deepcopy(self.good)
        raw.update(object_description=group['object_description'],object_scope=group['object_scope'],
            object_references=[{'source_unit_key':group['object_references'][0]['source_unit_key']}],
            member_assertions={m['source_unit_key']:{'role':m['role'],'same_specific_system':True,
                'affirmed_assertions':['当前段明示事实'] if m['role']=='facts' else [],'rejected_options':[],'confidence':.95} for m in members})
        candidate,issues=v.decision(raw,entries,selected)
        self.assertFalse(issues)
        a=next(i for i,e in enumerate(entries) if e['source_unit_key']==selected[0]['source_unit_key'])
        b=next(i for i,e in enumerate(entries) if e['source_unit_key']==selected[-1]['source_unit_key'])
        validator=recovery.partition_validator(f.doc,f.plan,f.segments,entries,a,b,ranges.apply)
        self.assertFalse(validator(candidate))
        raw=copy.deepcopy(self.good);del raw['why']
        self.assertTrue(v.decision(raw,self.entries,self.entries)[1])

if __name__=='__main__':unittest.main()
