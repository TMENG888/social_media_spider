import copy
import unittest
from prose_audit_references import payload,verify


class OpaqueProseAuditTests(unittest.TestCase):
    def setUp(self):
        self.source='【父评论｜甲】没听见。雨天也没听见。【子评论1｜乙】谢谢。【子评论2｜丙】开窗能听见，但不影响生活。'
        self.prose='丙称开窗能听见飞机声，但不影响生活。'
        self.p=payload(self.source,self.prose)
        self.key=self.p['source_evidence_catalog'][-1]['source_key']
        self.response={'checks':[{'prose_key':self.p['prose_catalog'][0]['prose_key'],
            'status':'supported','source_keys':[self.key],'why':'原文丙明确给出条件和影响','confidence':.95}],
            'coverage':{'captures_primary_points':True,'source_keys':[self.key],
                        'why':'主要事实及影响限定已保留','confidence':.95}}

    def test_disjoint_references_preserve_nonmatching_source_position(self):
        okay,audit=verify(self.source,self.prose,self.response)
        self.assertTrue(okay)
        self.assertIn('不影响生活',audit[0]['verified_source_quote'])
        self.assertNotIn('evidence_id',str(self.p))
        self.assertEqual('丙',self.p['source_evidence_catalog'][-1]['speaker'])
    def test_positive_model_audit_cannot_waive_explicit_impact_omission(self):
        prose='丙称开窗能听见飞机声。'
        p=payload(self.source,prose);r=copy.deepcopy(self.response)
        r['checks'][0]['prose_key']=p['prose_catalog'][0]['prose_key']
        okay,audit=verify(self.source,prose,r)
        self.assertFalse(okay)
        self.assertTrue(any('生活影响限定' in c.get('reason','') for c in audit))

    def test_prose_key_cannot_be_source_key(self):
        r=copy.deepcopy(self.response);r['checks'][0]['source_keys']=[r['checks'][0]['prose_key']]
        self.assertFalse(verify(self.source,self.prose,r)[0])

    def test_source_ordinal_cannot_be_used(self):
        for keys in ([4],['4'],[self.key,self.key]):
            r=copy.deepcopy(self.response);r['checks'][0]['source_keys']=keys
            self.assertFalse(verify(self.source,self.prose,r)[0])

    def test_missing_duplicate_and_unknown_prose_keys_fail(self):
        for checks in ([],self.response['checks']*2,[dict(self.response['checks'][0],prose_key='PROSE-unknown')]):
            r=copy.deepcopy(self.response);r['checks']=checks
            self.assertFalse(verify(self.source,self.prose,r)[0])

    def test_reviewer_rejection_cannot_be_overridden_by_legal_keys(self):
        r=copy.deepcopy(self.response);r['checks'][0]['status']='unsupported'
        self.assertFalse(verify(self.source,self.prose,r)[0])

    def test_coverage_failure_and_low_confidence_remain_failures(self):
        r=copy.deepcopy(self.response);r['coverage']['captures_primary_points']=False
        self.assertFalse(verify(self.source,self.prose,r)[0])
        r=copy.deepcopy(self.response);r['checks'][0]['confidence']=.89
        self.assertFalse(verify(self.source,self.prose,r)[0])


if __name__=='__main__':unittest.main()
