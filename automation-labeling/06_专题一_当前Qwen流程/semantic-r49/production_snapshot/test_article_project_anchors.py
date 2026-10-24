import unittest
from article_project_anchors import recover

class ProjectAnchors(unittest.TestCase):
    def test_multi_project_not_collapsed_or_guessed(self):
        projects=[{'id':'A','aliases':['海晏']},{'id':'B','aliases':['臻澐']}]
        out=recover({'_excerpt':'海晏与臻澐对比','project_ids':[]},projects)
        self.assertEqual(['A','B'],out['project_ids'])
        self.assertEqual(['海晏','臻澐'],[x['evidence'] for x in out['project_evidence']])
    def test_no_keyword_inheritance_and_alias_conflict(self):
        projects=[{'id':'A','aliases':['共同名']},{'id':'B','aliases':['共同名']}]
        self.assertEqual([],recover({'_excerpt':'采光良好','project_ids':[]},projects)['project_ids'])
        out=recover({'_excerpt':'共同名采光好','project_ids':[]},projects)
        self.assertEqual([],out['project_ids']);self.assertTrue(out['uncertainties'])

if __name__=='__main__':unittest.main()
