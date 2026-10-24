import unittest
from scope_countercheck import confirmed_exclusion
class Scope(unittest.TestCase):
    def test_uncertain_negative_is_not_excluded(self):
        self.assertFalse(confirmed_exclusion({'exclude':False,'why':'购房选择评价','confidence':.99,'evidence_ids':[1]}, {1}))
        self.assertFalse(confirmed_exclusion({'exclude':True,'why':'缺事实','confidence':.8,'evidence_ids':[1]}, {1}))
    def test_valid_irrelevant_requires_source_reference(self):
        response={'exclude':True,'why':'只有招聘','confidence':.95,'evidence_ids':[1]}
        self.assertTrue(confirmed_exclusion(response,{1}))
        for ids in ([2],['1'],[True],[]):self.assertFalse(confirmed_exclusion(dict(response,evidence_ids=ids),{1}))
if __name__=='__main__':unittest.main()
