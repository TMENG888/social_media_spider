import copy
import unittest
from delivery_label_reference_v91 import display_emphases, display_schema, enrich_rows, TAG_KEYS


def tag(tid='VOC-0001', emphasis='采光'):
    return dict(zip(TAG_KEYS,[tid,1,'产品','户型','通用','采光',None,emphasis]))


class LabelReferenceTests(unittest.TestCase):
    def test_multiple_labels_preserve_order(self):
        self.assertEqual(display_emphases([tag(emphasis='朝向'),tag('VOC-0002','采光')]),'朝向;采光')

    def test_duplicate_display_words_do_not_remove_tags(self):
        rows=[{'unit_id':'u','标签明细':[tag(),tag('VOC-0002')],'备注':'原备注'}]
        reference=[tag(),tag('VOC-0002')]
        old=copy.deepcopy(rows)
        out=enrich_rows(rows,reference)
        self.assertEqual(out[0]['标签强调方向'],'采光')
        self.assertEqual(out[0]['标签明细'],old[0]['标签明细'])
        self.assertEqual(rows,old)
        self.assertIsNot(out[0]['标签明细'],rows[0]['标签明细'])

    def test_empty_and_null_not_fabricated(self):
        self.assertEqual(display_emphases([]),'')
        self.assertEqual(display_emphases([tag(emphasis=None)]),'')

    def test_unknown_id_rejected_without_mutation(self):
        rows=[{'标签明细':[tag()]}]
        old=copy.deepcopy(rows)
        with self.assertRaises(ValueError):enrich_rows(rows,[])
        self.assertEqual(rows,old)

    def test_changed_dictionary_value_is_not_repaired_by_export(self):
        changed=tag();changed['三级标签']='编造对象'
        with self.assertRaises(ValueError):enrich_rows([{'标签明细':[changed]}],[tag()])

    def test_extra_keys_rejected(self):
        changed=tag();changed['置信度']=.99
        with self.assertRaises(ValueError):enrich_rows([{'标签明细':[changed]}],[tag()])

    def test_number_type_is_exact(self):
        changed=tag();changed['标签编号']='1'
        with self.assertRaises(ValueError):enrich_rows([{'标签明细':[changed]}],[tag()])

    def test_schema_preserves_required_neighbors(self):
        schema=['unit_id','打标说明','标签明细','观点摘要','备注','验收状态']
        new=display_schema(schema)
        self.assertEqual(new,['unit_id','打标说明','标签明细','标签强调方向','观点摘要','备注','验收状态'])
        self.assertEqual(schema,['unit_id','打标说明','标签明细','观点摘要','备注','验收状态'])
        self.assertEqual(display_schema(new),new)

    def test_invalid_data_is_not_hidden(self):
        for value in ('[]',None,{},[None],[tag(emphasis=3)]):
            with self.subTest(value=value),self.assertRaises(ValueError):display_emphases(value)


if __name__=='__main__':unittest.main()
