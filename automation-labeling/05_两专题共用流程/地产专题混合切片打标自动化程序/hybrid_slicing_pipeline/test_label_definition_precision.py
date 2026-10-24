import unittest
import delivery_v6 as registry
import delivery_v11 as pipeline
import label_definition_precision as precision


class DefinitionPrecision(unittest.TestCase):
    def test_hierarchy_is_input_only_and_missing_levels_are_null(self):
        tag={'tag_id':'VOC-0001','l1':'产品','l2':'公区','l3':'会所','l4':'会所功能','l5':'健身房器械',
             'emphasis':'健身房器械','instruction':'记录器械','topics':['test']}
        entry=registry.catalogue([tag],'test')[0]
        self.assertEqual(['产品','公区','会所','会所功能','健身房器械'],entry['标签对象路径'])
        self.assertEqual('D0001',entry['choice_key'])
        self.assertNotIn('tag_id',entry)
        self.assertEqual(['产品',None,None,None,None],precision.path({'l1':'产品'}))

    def test_final_definition_review_gets_same_counterexamples(self):
        self.assertIn(precision.INSTRUCTION,pipeline.VERIFY_SYSTEM)
        self.assertIn('label_definition_precision.py',pipeline.IMPLEMENTATION_FILES)


if __name__=='__main__':unittest.main()
