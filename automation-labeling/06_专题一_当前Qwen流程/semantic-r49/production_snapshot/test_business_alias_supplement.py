import unittest
from business_alias_supplement import apply
from explicit_comment_project_evidence import direct_name_supported


class SupplementTests(unittest.TestCase):
    def test_actual_canonical_dictionary_short_name(self):
        business={'projects':[{'id':'P01','name':'北京臻澐','aliases':['北京臻澐','华润臻澐']}]}
        fixed=apply(business)
        self.assertTrue(direct_name_supported('北京臻澐','海淀实景豪宅臻澐','海淀实景豪宅臻澐',fixed['projects']))
        self.assertNotIn('臻澐',business['projects'][0]['aliases'])

    def test_different_configuration_not_guessed(self):
        business={'projects':[{'id':'P01','name':'另一个项目','aliases':[]}]}
        self.assertEqual(apply(business),business)

    def test_conflicting_name_not_assigned(self):
        business={'projects':[{'id':'P01','name':'北京臻澐','aliases':[]},
                              {'id':'P99','name':'其他臻澐','aliases':['臻澐']}]}
        fixed=apply(business)
        self.assertNotIn('臻澐',fixed['projects'][0]['aliases'])
        self.assertEqual(fixed['alias_supplement_audit'][0]['status'],'collision')


if __name__=='__main__':unittest.main()
