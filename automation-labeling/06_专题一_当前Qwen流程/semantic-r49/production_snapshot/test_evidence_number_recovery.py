import unittest
from evidence_number_recovery import apply
from label_evidence_reference import evidence_catalog


class EvidenceRecovery(unittest.TestCase):
    def check(self,ids=None):
        result={'choice_key':'D0074','status':'supported','why':'作者明确说贵','confidence':.95}
        if ids is not None:result['evidence_ids']=ids
        return result
    def test_missing_reference_not_success(self):
        good,bad=apply({'checks':[self.check()]},{'D0074'},evidence_catalog('太贵了。'))
        self.assertEqual([],good);self.assertEqual({'D0074'},bad)
    def test_valid_reference_exact_source(self):
        good,bad=apply({'checks':[self.check([1])]},{'D0074'},evidence_catalog('太贵了。'))
        self.assertFalse(bad);self.assertEqual('太贵了。',good[0]['direct_quote'])
    def test_unknown_or_string_ids_not_coerced(self):
        for ids in ([2],['1'],[1,1]):
            self.assertEqual({'D0074'},apply({'checks':[self.check(ids)]},{'D0074'},evidence_catalog('太贵了。'))[1])
    def test_good_decision_not_erased_by_other_missing_key(self):
        good,bad=apply({'checks':[self.check([1])]},{'D0074','D0076'},evidence_catalog('太贵了。'))
        self.assertEqual(1,len(good));self.assertEqual({'D0076'},bad)
    def test_unsupported_needs_no_reference(self):
        c=self.check();c['status']='unsupported'
        good,bad=apply({'checks':[c]},{'D0074'},evidence_catalog('你好'))
        self.assertFalse(bad);self.assertEqual('unsupported',good[0]['status'])


if __name__=='__main__':unittest.main()
