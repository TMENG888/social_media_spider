import unittest
import duplicate_target_projection_v59 as v

class TargetProjectionTests(unittest.TestCase):
    def setUp(self):
        self.a='甲苑同一户型为四居洋房。';self.b='甲苑这一户型为低密洋房。'
        a,b=v.catalogs(self.a,self.b)
        fact=lambda key:{'object':'甲苑同一户型','value':'洋房','evidence_keys':[key],'qualifiers':[]}
        self.r={'target_property':'物业形态/洋房','facts_a':[fact(a[0]['source_key'])],
            'facts_b':[fact(b[0]['source_key'])],'same_object':True,'different_in_target_property':False,
            'ignored_other_properties':['四居','低密'],'verdict':'same_fact','whole_label_removable':True,
            'keep_side':'A','why':'同一户型物业类型一致，房间数与密度不改变该标签事实','confidence':.95}

    def test_same_target_property_can_remove_one_tag(self):
        result,issues=v.verify(self.a,self.b,self.r)
        self.assertFalse(issues);self.assertTrue(result['safe_to_remove'])

    def test_other_attribute_difference_cannot_be_different_fact(self):
        self.r.update(verdict='different_fact',keep_side=None,whole_label_removable=False)
        self.assertIsNone(v.verify(self.a,self.b,self.r)[0])

    def test_different_object_keeps_equal_values(self):
        self.r.update(verdict='different_fact',same_object=False,keep_side=None,whole_label_removable=False)
        result,issues=v.verify(self.a,self.b,self.r)
        self.assertFalse(issues);self.assertFalse(result['safe_to_remove'])

    def test_partial_overlap_never_whole_tag_drop(self):
        self.r.update(verdict='partial_overlap',keep_side=None)
        self.assertIsNone(v.verify(self.a,self.b,self.r)[0])
        self.r['whole_label_removable']=False
        self.assertFalse(v.verify(self.a,self.b,self.r)[0]['safe_to_remove'])

    def test_low_confidence_cannot_drop(self):
        self.r['confidence']=.89
        self.assertFalse(v.verify(self.a,self.b,self.r)[0]['safe_to_remove'])

    def test_cross_side_source_key_fails(self):
        self.r['facts_b'][0]['evidence_keys']=self.r['facts_a'][0]['evidence_keys']
        self.assertIsNone(v.verify(self.a,self.b,self.r)[0])

    def test_missing_projection_is_not_defaulted(self):
        self.r.pop('different_in_target_property')
        self.assertIsNone(v.verify(self.a,self.b,self.r)[0])

if __name__=='__main__':unittest.main()
