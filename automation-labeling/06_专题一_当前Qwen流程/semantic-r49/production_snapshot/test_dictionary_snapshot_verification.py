import unittest
from verify_dictionary_backfill_v8 import verify


class DictionarySnapshot(unittest.TestCase):
    def fixture(self):
        original={'tag_id':'VOC-1','source_number':'1','topics':['专题甲'],
            'emphasis':'方向','l1':'产品','l2':'户型','l3':'通用','l4':'数量','l5':''}
        tag={'标签路径ID':'VOC-1','标签编号':1,'一级标签':'产品','二级标签':'户型',
            '三级标签':'通用','四级标签':'数量','五级标签':None,'标签强调方向':'方向'}
        data={'results':[{'document':{'topic':'专题甲'},'rows':[{'unit_id':'u','标签明细':[tag]}]}]}
        return data, {'VOC-1':original}, tag

    def test_partial_scope_is_explicit(self):
        data,dictionary,_=self.fixture()
        report=verify(data,dictionary)
        self.assertFalse(report['errors'])
        self.assertIn('非全批完成证明',report['verification_scope'])
        self.assertEqual(1,report['checked_sources'])

    def test_cross_topic_rejected(self):
        data,dictionary,_=self.fixture()
        data['results'][0]['document']['topic']='专题乙'
        self.assertTrue(verify(data,dictionary)['errors'])

    def test_extra_json_key_rejected(self):
        data,dictionary,tag=self.fixture()
        tag['置信度']=.99
        self.assertTrue(verify(data,dictionary)['errors'])

    def test_unknown_id_rejected(self):
        data,dictionary,tag=self.fixture()
        tag['标签路径ID']='非法'
        self.assertTrue(verify(data,dictionary)['errors'])


if __name__=='__main__':unittest.main()
