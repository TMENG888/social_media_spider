import unittest
from verify_comment_comparison_qualifiers_v59 import inspect

class ComparisonQualifierTests(unittest.TestCase):
    def data(self,summary):
        return {'results':[{'document':{'record_id':'T2-C-7963753211120747279','text':'完整原文'},
            'rows':[{'原始摘录':'完整原文','观点摘要':summary}]}]}
    def test_missing_source_and_blank_do_not_pass(self):
        self.assertTrue(inspect({'results':[]})['errors']);self.assertTrue(inspect(self.data(''))['errors'])
    def test_actual_overgeneralization_fails(self):
        self.assertTrue(inspect(self.data('熙瑞与西冉噪音总体差不多，但东地块道路影响较大'))['errors'])
    def test_local_geographical_scope_preserved(self):
        self.assertFalse(inspect(self.data('熙瑞西地块与西冉北地块噪音总体差不多，东地块道路影响更多'))['errors'])
    def test_omitted_secondary_comparison_does_not_invent_failure(self):
        self.assertFalse(inspect(self.data('回复者认为熙瑞东地块主干路影响更多，西冉南地块最差'))['errors'])

if __name__=='__main__':unittest.main()
