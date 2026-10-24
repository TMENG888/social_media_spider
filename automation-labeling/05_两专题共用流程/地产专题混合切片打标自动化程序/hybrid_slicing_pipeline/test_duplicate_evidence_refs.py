import unittest
from duplicate_evidence_refs import resolve
class DuplicateReferences(unittest.TestCase):
    def test_each_quote_owned_by_its_unit(self):
        units=[{'excerpt':'甲项目一梯一户。'},{'excerpt':'乙项目双阳台。'}]
        out=resolve({'checks':[{'pair_id':0,'evidence_ids_a':[1],'evidence_ids_b':[1]}]},units,[{'unit_a':0,'unit_b':1}])
        self.assertEqual('甲项目一梯一户。',out['checks'][0]['quote_a'])
        self.assertEqual('乙项目双阳台。',out['checks'][0]['quote_b'])
    def test_invalid_reference_cannot_import_other_unit(self):
        out=resolve({'checks':[{'pair_id':0,'evidence_ids_a':[2],'evidence_ids_b':[1]}]},
            [{'excerpt':'甲配置'},{'excerpt':'乙配置'}],[{'unit_a':0,'unit_b':1}])
        self.assertIsNone(out['checks'][0]['quote_a'])
if __name__=='__main__':unittest.main()
