import copy,unittest
from unittest.mock import patch
import article_local_alias_review_v55 as v

class LocalAliasEvidence(unittest.TestCase):
    def setUp(self):
        self.projects=[{'id':'C1','aliases':['甲企云庭'],'name':'甲企云庭'}]
        self.catalog=[{'source_key':'A','text':'介绍甲企云庭。'},{'source_key':'B','text':'云庭的层高为3米。'}]
        self.alias={'project_id':'C1','short_name':'云庭','formal_source_key':'A','short_source_key':'B','why':'本篇全称后明确简称','confidence':.95}
        self.doc={'kind':'文章','topic':'北京臻澐项目口碑','text':'介绍甲企云庭。云庭的层高为3米。'}
    def test_program_materializes_actual_source(self):
        raw={'aliases':[self.alias]};original=copy.deepcopy(raw)
        out,issues=v.materialize(raw,self.doc,self.projects,self.catalog)
        self.assertFalse(issues);self.assertEqual(original,raw)
        self.assertEqual(self.catalog[0]['text'],out[0]['formal_source_text'])
    def test_unknown_fake_quote_wrong_suffix_and_ambiguous_short_rejected(self):
        for change in ({'formal_source_key':'X'},{'short_name':'甲企'},{'short_name':'不存在'},{'confidence':.8}):
            raw={'aliases':[dict(self.alias,**change)]}
            self.assertTrue(v.materialize(raw,self.doc,self.projects,self.catalog)[1])
        self.projects.append({'id':'C2','aliases':['乙企云庭']})
        self.assertTrue(v.materialize({'aliases':[self.alias]},self.doc,self.projects,self.catalog)[1])
    def exercise(self,approve):
        raw={'aliases':[self.alias]}
        class Runner:
            def __init__(self):self.calls=0
            def call(self,*args,**kwargs):
                self.calls+=1
                if self.calls==1:return raw,{'status':'success'}
                return {'checks':[{'alias_key':'ALIAS-0','approved':approve,'why':'原文独立核查','confidence':.95}]},{'status':'success'}
        business={'projects':copy.deepcopy(self.projects)};original=copy.deepcopy(business);runner=Runner()
        with patch.object(v,'source_catalog',return_value=self.catalog):out,audit,calls,issues=v.review(self.doc,business,runner)
        self.assertFalse(issues);self.assertEqual(original,business);self.assertEqual(2,runner.calls)
        return out
    def test_fresh_approval_is_local_not_global(self):
        self.assertIn('云庭',self.exercise(True)['projects'][0]['aliases'])
        self.assertEqual(['甲企云庭'],self.projects[0]['aliases'])
    def test_rejection_cannot_add_alias(self):
        self.assertNotIn('云庭',self.exercise(False)['projects'][0]['aliases'])
    def test_comments_do_not_borrow_alias_or_parent_facts_here(self):
        class Runner:
            def call(self,*args,**kwargs):raise AssertionError('no article aliases on comment')
        b={'projects':self.projects};self.assertEqual((b,[],[],[]),v.review(dict(self.doc,kind='评论'),b,Runner()))

if __name__=='__main__':unittest.main()
