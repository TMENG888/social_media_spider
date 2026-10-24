import unittest
from delivery_v85 import exact_fragments,locate_partition,schema,coverage_statistics
from bounded_visible_contract_v60 import contract

class RepairContract(unittest.TestCase):
    def test_disconnected_evidence_is_located_individually(self):
        spans,errors=exact_fragments(['120㎡','均为建筑面积'],'120㎡户型，以上均为建筑面积')
        self.assertFalse(errors);self.assertEqual(len(spans),2)

    def test_ellipsis_is_not_literal_evidence(self):
        spans,errors=exact_fragments(['120㎡...均为建筑面积'],'120㎡户型，以上均为建筑面积')
        self.assertTrue(errors);self.assertEqual(spans,[])

    def test_cannot_borrow_outside_attribute(self):
        spans,errors=exact_fragments(['30米'],'甲户型30米；乙户型12米',8,14)
        self.assertTrue(errors)

    def test_merge_only_contiguous_model_groups(self):
        seg=[{'start':0,'end':2},{'start':2,'end':4},{'start':4,'end':6}]
        ranges,errors=locate_partition({'units':[{'segment_indices':[0,1]},{'segment_indices':[2]}]},'abcdef','文章',seg)
        self.assertFalse(errors);self.assertEqual(ranges,[(0,4),(4,6)])

    def test_cannot_skip_source_range(self):
        _,errors=locate_partition({'units':[{'segment_indices':[0]}]},'abcd','文章',[{'start':0,'end':2},{'start':2,'end':4}])
        self.assertTrue(errors)

    def test_comments_not_split(self):
        _,errors=locate_partition({'units':[{'segment_indices':[0]},{'segment_indices':[1]}]},'abcd','评论',[{'start':0,'end':2},{'start':2,'end':4}])
        self.assertIn('评论不允许拆分',errors)

    def test_schema_arrays_do_not_share_namespace(self):
        s=contract(schema({'D0001':{}}),{'source_catalog':[{'source_key':'SRC-X'}]})
        u=s['properties']['units']['items']['properties'];t=u['labels']['items']['properties']
        self.assertEqual(t['source_keys']['items']['enum'],['SRC-X'])
        self.assertNotIn('enum',t['property_quotes']['items'])
        self.assertEqual(u['emotions']['items']['enum'],['无态度','中性','正向','负向'])

    def test_zero_index_is_not_missing(self):
        doc={'topic':'T2','kind':'评论','row':{'平台':'小红书'},'parent':{'热度指数':'0','互动深度指数':''}}
        s=coverage_statistics([{'document':doc,'complete':True,'rows':[]}])[0]
        self.assertEqual(s['热度可计算数'],1);self.assertEqual(s['互动可计算数'],0)

if __name__=='__main__':unittest.main()
