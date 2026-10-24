import unittest
import full_dictionary_selection_v59 as v

class FullDictionarySelectionTests(unittest.TestCase):
    def setUp(self):
        self.text='景观为现代中式。'
        self.index={'A':{'emphasis':'景观风格','l3':'景观','instruction':'园林风格'},
                    'B':{'emphasis':'整体设计','l3':'装修风格','instruction':'住宅精装风格'}}
        keys=[v.source_catalog(self.text)[0]['source_key']]
        self.r={'labels':[{'choice_key':'A','source_keys':keys,'object_keys':keys,'why':'原文讲园林','confidence':.95}],
                'unmatched_facts':[]}
    def test_all_dictionary_supplied_not_keyword_filtered(self):
        self.assertEqual({x['choice_key'] for x in v.payload(self.text,self.index)['all_applicable_labels']},{'A','B'})
    def test_definition_backfill_from_dictionary(self):
        selected,errors=v.materialize(self.text,self.index,self.r)
        self.assertFalse(errors);self.assertEqual(selected[0]['dictionary_definition'],self.index['A'])
    def test_model_cannot_create_illegal_key(self):
        self.r['labels'][0]['choice_key']='not-allowed'
        self.assertFalse(v.materialize(self.text,self.index,self.r)[0])
    def test_duplicate_key_not_multiple_output_rows(self):
        self.r['labels']*=2
        self.assertTrue(v.materialize(self.text,self.index,self.r)[1])
    def test_forged_evidence_not_repaired_silently(self):
        self.r['labels'][0]['source_keys']=['SRC-imagined']
        self.assertFalse(v.materialize(self.text,self.index,self.r)[0])
    def test_empty_valid_selection_keeps_unmatched_facts(self):
        self.assertEqual(v.materialize(self.text,self.index,{'labels':[],'unmatched_facts':['无适用定义的事实']}),([],[]))

if __name__=='__main__':unittest.main()
