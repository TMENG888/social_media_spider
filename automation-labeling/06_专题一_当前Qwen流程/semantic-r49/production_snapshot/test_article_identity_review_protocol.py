import copy
import unittest
import article_identity_references as refs
import article_identity_review_protocol as protocol


class Runner:
    def __init__(self,responses):self.responses=iter(responses);self.payloads=[]
    def call(self,system,payload,doc,phase):
        self.payloads.append(copy.deepcopy(payload))
        return next(self.responses),{'status':'success','phase':phase}


class IdentityProtocol(unittest.TestCase):
    def setUp(self):
        self.doc={'text':'甲项目。户型面积免责声明。'}
        self.catalog=refs.catalog(self.doc['text'],['甲项目'])
        self.units=[{'source_end_id':1}];self.segments=[{'end':len(self.doc['text'])}]
        self.slices=[{'unit_index':0,'excerpt':'户型面积免责声明。'}]
        self.valid={'contexts':[{'unit_index':0,'assigned':True,
                    'identity_key':self.catalog[0]['source_key'],'why':'明确单项目连续承接','confidence':.95}]}

    def run_review(self,responses):
        runner=Runner(responses)
        result=protocol.review(self.doc,self.units,self.segments,self.catalog,self.slices,runner)
        return result,runner

    def test_missing_confidence_has_bounded_recovery(self):
        bad=copy.deepcopy(self.valid);del bad['contexts'][0]['confidence']
        (units,audit,calls),runner=self.run_review([bad,self.valid])
        self.assertEqual('甲项目',units[0]['object_quote']);self.assertEqual(2,len(calls))
        self.assertTrue(audit['attempts'][0]['protocol_issues']);self.assertFalse(audit['protocol_issues'])
        self.assertEqual(self.doc['text'],runner.payloads[1]['source_text'])

    def test_still_missing_confidence_never_approved(self):
        bad=copy.deepcopy(self.valid);del bad['contexts'][0]['confidence']
        (units,audit,calls),_=self.run_review([bad,bad])
        self.assertIsNone(units[0]['object_quote']);self.assertEqual(2,len(calls));self.assertTrue(audit['protocol_issues'])

    def test_low_semantic_confidence_not_defaulted_or_retried(self):
        low=copy.deepcopy(self.valid);low['contexts'][0]['confidence']=.7
        (units,audit,calls),_=self.run_review([low])
        self.assertIsNone(units[0]['object_quote']);self.assertEqual(1,len(calls));self.assertTrue(audit['identity_issues'])

    def test_explicit_unassigned_stays_unassigned(self):
        no={'contexts':[{'unit_index':0,'assigned':False,'identity_key':None,'why':'多对象指代不明','confidence':.95}]}
        (units,audit,calls),_=self.run_review([no])
        self.assertIsNone(units[0]['object_quote']);self.assertEqual(1,len(calls))

    def test_illegal_index_and_boolean_confidence_rejected(self):
        bad=copy.deepcopy(self.valid);bad['contexts'][0].update(unit_index=1,confidence=True)
        self.assertTrue(protocol.protocol_issues(bad,1,self.catalog))

    def test_identity_fact_conflict_rechecked_not_auto_assigned(self):
        conflict={'contexts':[{'unit_index':0,'assigned':False,'identity_key':None,
            'why':'虽然关联前文项目，但未重复项目名称，配置不能借用','confidence':.5}]}
        (units,audit,calls),_=self.run_review([conflict,self.valid])
        self.assertEqual(2,len(calls));self.assertEqual('甲项目',units[0]['object_quote'])
        self.assertTrue(audit['attempts'][0]['semantic_conflict_leads'])
        self.assertFalse(audit['semantic_conflict_leads'])

    def test_persistent_semantic_conflict_never_assigns_identity(self):
        conflict={'contexts':[{'unit_index':0,'assigned':False,'identity_key':None,
            'why':'虽然关联前文项目，但未重复项目名称，配置不能借用','confidence':.5}]}
        (units,audit,calls),_=self.run_review([conflict,conflict])
        self.assertEqual(2,len(calls));self.assertIsNone(units[0]['object_quote'])
        self.assertTrue(audit['semantic_conflict_leads']);self.assertTrue(audit['identity_issues'])


if __name__=='__main__':unittest.main()
