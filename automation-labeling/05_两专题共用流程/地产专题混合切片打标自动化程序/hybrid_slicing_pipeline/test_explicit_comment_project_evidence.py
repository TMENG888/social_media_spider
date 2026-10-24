import unittest
from explicit_comment_project_evidence import direct_name_supported


class DirectCommentProjectTests(unittest.TestCase):
    projects=[{'id':'P01','name':'北京臻澐','aliases':['臻澐']},
              {'id':'C05','name':'保利熙瑞','aliases':['熙瑞']}]

    def test_direct_name_does_not_require_parent_body_repeat(self):
        self.assertTrue(direct_name_supported('北京臻澐','海淀实景豪宅臻澐','春节探盘｜海淀实景豪宅臻澐',self.projects))

    def test_implicit_comment_is_not_direct_proof(self):
        self.assertFalse(direct_name_supported('北京臻澐','想去','想去',self.projects))

    def test_parent_fact_cannot_be_quote(self):
        self.assertFalse(direct_name_supported('北京臻澐','臻澐会所','想去',self.projects))

    def test_other_project_does_not_support_requested_name(self):
        self.assertFalse(direct_name_supported('北京臻澐','熙瑞交通不好','熙瑞交通不好',self.projects))

    def test_external_named_project_keeps_identity_only(self):
        self.assertTrue(direct_name_supported('西冉地块','西冉地块很吵','西冉地块很吵',self.projects))

    def test_shared_alias_cannot_select_one(self):
        dictionary=self.projects+[{'id':'P02','name':'另一臻澐','aliases':['臻澐']}]
        self.assertFalse(direct_name_supported('北京臻澐','臻澐','臻澐',dictionary))

    def test_whitespace_alignment(self):
        self.assertTrue(direct_name_supported('北京臻澐','臻澐','看了 臻澐',self.projects))

    def test_author_nickname_is_not_project_evidence(self):
        self.assertFalse(direct_name_supported('北京臻澐','【父评论｜臻澐销售】想去','【父评论｜臻澐销售】想去',self.projects))


if __name__=='__main__':unittest.main()
