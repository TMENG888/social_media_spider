import unittest
import catalogued_boundary_v65 as v
import delivery_v11 as p


class PositionTests(unittest.TestCase):
    def unit(self,key,phrase=None,n=1):
        return {'start_source_key':key,'start_phrase':phrase,'start_occurrence':n,
                'object':'明确对象','theme':'完整主题','why':'对象转换','confidence':.95,'uncertainties':[]}

    def test_inside_one_catalogue_entry_can_have_multiple_model_boundaries(self):
        text='甲园林有绿植乙会所设泳池茶室'
        entries=[{'source_key':'K1','start':0,'end':len(text),'text':text}]
        raw={'units':[self.unit('K1'),self.unit('K1','乙会所')]}
        plan,segments,errors=v.materialize(text,entries,raw,p.quote_partition)
        self.assertFalse(errors)
        self.assertEqual([s['text'] for s in segments],['甲园林有绿植','乙会所设泳池茶室'])
        self.assertEqual(''.join(s['text'] for s in segments),text)

    def test_duplicate_phrase_uses_catalogue_local_occurrence(self):
        text='会所甲介绍会所乙介绍'
        entries=[{'source_key':'K1','start':0,'text':text}]
        raw={'units':[self.unit('K1'),self.unit('K1','会所',2)]}
        self.assertEqual(v.positions(text,entries,raw),([0,5],[]))

    def test_unlocatable_phrase_is_not_manually_repaired(self):
        text='甲对象介绍'
        entries=[{'source_key':'K1','start':0,'text':text}]
        raw={'units':[self.unit('K1','不存在的文字')]}
        self.assertTrue(v.positions(text,entries,raw)[1])

    def test_first_start_and_order_enforced(self):
        entries=[{'source_key':'K1','start':0,'text':'甲乙丙'}]
        self.assertTrue(v.positions('甲乙丙',entries,{'units':[self.unit('K1','乙') ]})[1])


if __name__=='__main__':unittest.main()
