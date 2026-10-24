import unittest
import literal_article_names_v59 as v

class LiteralNamesTests(unittest.TestCase):
    def setUp(self):
        self.source='甲企·湖岸雅庭位于甲城，旁边有乙企江畔华庭。'
        self.keys=[v.source_catalog(self.source)[0]['source_key']]
        self.r={'names':[{'name_quote':'甲企·湖岸雅庭','source_keys':self.keys,'why':'原文明示住宅案名','confidence':.95}]}
    def test_literal_separator_preserved(self):
        names,issues=v.materialize(self.source,self.r)
        self.assertFalse(issues);self.assertEqual(names[0]['name'],'甲企·湖岸雅庭')
    def test_rewritten_name_not_silently_normalized(self):
        self.r['names'][0]['name_quote']='甲企湖岸雅庭'
        self.assertFalse(v.materialize(self.source,self.r)[0])
    def test_unknown_source_key_not_replaced(self):
        self.r['names'][0]['source_keys']=['SRC-unknown']
        self.assertFalse(v.materialize(self.source,self.r)[0])
    def test_low_confidence_not_defaulted(self):
        self.r['names'][0]['confidence']=.8
        self.assertFalse(v.materialize(self.source,self.r)[0])
    def test_no_name_valid_without_forced_candidate(self):self.assertEqual(v.materialize(self.source,{'names':[]}),([],[]))

if __name__=='__main__':unittest.main()
