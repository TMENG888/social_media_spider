import unittest
import delivery_quality_helpers as q


class AcceptanceHelpers(unittest.TestCase):
    def test_pseudo_null_is_not_a_summary(self):
        for value in (None,'',' ','null',' NULL ','None','NaN','undefined',0):
            self.assertTrue(q.missing_prose(value))
        for value in ('采光不错','作者提到英文null值'):
            self.assertFalse(q.missing_prose(value))

    def test_slice_uncertainty_does_not_contaminate_another_slice(self):
        a={'self_check':{'pass':True,'issues':[]},'uncertainties':[]}
        b=q.scope_acceptance(a,{'issues':['当前会所对象待核'],'ambiguous':[]})
        self.assertFalse(b['self_check']['pass'])
        self.assertTrue(a['self_check']['pass'])
        c=q.scope_acceptance(a,{'issues':[],'ambiguous':[]})
        self.assertEqual([],c['uncertainties'])

    def test_ambiguity_reason_is_available_on_its_own_slice(self):
        output=q.scope_acceptance({'self_check':{'pass':True}},
            {'ambiguous':[{'choice_key':'D0145','reason':'高速不证明高速入口'}]})
        self.assertIn('高速不证明高速入口',output['self_check']['issues'][0])

    def test_canonical_name_requires_unique_registered_alias(self):
        projects=[{'name':'北京臻澐','aliases':['北京臻澐','华润臻澐']}]
        self.assertTrue(q.project_name_is_grounded('北京臻澐','想去','华润臻澐会所',projects))
        self.assertFalse(q.project_name_is_grounded('北京臻澐','想去','保利熙瑞会所',projects))
        self.assertFalse(q.project_name_is_grounded('未知项目','想去','华润臻澐会所',projects))
        projects.append({'name':'北京臻澐','aliases':['华润臻澐']})
        self.assertFalse(q.project_name_is_grounded('北京臻澐','想去','华润臻澐会所',projects))


if __name__=='__main__':unittest.main()
