import unittest
from pathlib import Path
from multilabel_v3 import (PostIndex,numeric_score,make_doc,attach_delivery,keyword_match,
                          DELIVERY_FIELDS,REMOVED_FIELDS,T1,T2,load_taxonomy,process_document)


class ContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.taxonomy=load_taxonomy(Path(__file__).parent/'resources/置地VOC标签体系_两专题打标版.xlsx')
        cls.posts=[{'id':'10','文章id':'ext-1','文章链接':'https://x/1','平台':'小红书','项目':T2,
                    '文章内容':'北京臻澐厨房配有冰箱。','热度指数':'0','互动深度指数':'67.25'},
                   {'id':'20','文章id':'ext-2','文章链接':'https://x/2','平台':'小红书','项目':T1,
                    '文章内容':'厨房配有冰箱。','热度指数':'88','互动深度指数':''}]

    def test_removed_root_fields(self):
        self.assertFalse(set(DELIVERY_FIELDS)&REMOVED_FIELDS)
        self.assertTrue({'标签明细','映射文章id','热度指数','互动深度指数'}<=set(DELIVERY_FIELDS))

    def test_post_maps_self_and_zero_is_preserved(self):
        doc=make_doc(self.posts[0]); row=attach_delivery(doc,{'start':0,'end':2,'excerpt':'北京','labels':[]})
        self.assertEqual(row['映射文章id'],'10');self.assertEqual(row['热度指数'],0)
        self.assertEqual(row['互动深度指数'],67.25)

    def test_comment_unique_id_mapping(self):
        comment={'id':'99','评论id':'external-comment','平台':'小红书','文章id':'ext-1','评论内容':'价格太高了','项目':T2}
        parent,status=PostIndex(self.posts).map_comment(comment)
        row=attach_delivery(make_doc(comment,'评论',parent,status),{'start':0,'end':6,'excerpt':'价格太高了','labels':[]})
        self.assertEqual(row['源表id'],'99');self.assertEqual(row['映射文章id'],'10')
        self.assertEqual(row['来源评论id'],'external-comment');self.assertEqual(row['热度指数'],0)

    def test_conflicting_comment_id_url(self):
        parent,status=PostIndex(self.posts).map_comment({'平台':'小红书','文章id':'ext-1','文章链接':'https://x/2'})
        self.assertIsNone(parent);self.assertIn('冲突',status)

    def test_missing_comment_mapping_does_not_make_zero(self):
        row={'id':'99','项目':T2,'平台':'小红书','评论内容':'价格太高了'}
        parent,status=PostIndex(self.posts).map_comment(row)
        record=attach_delivery(make_doc(row,'评论',parent,status),{'start':0,'end':6,'excerpt':'价格太高了','labels':[]})
        self.assertIsNone(record['映射文章id']);self.assertIsNone(record['热度指数'])

    def test_missing_metrics_remain_none(self):
        self.assertIsNone(numeric_score(''));self.assertIsNone(numeric_score('NaN'))
        self.assertIsNone(numeric_score('101'));self.assertEqual(numeric_score('0.00'),0)

    def test_matching_scans_all_devices_not_top_two(self):
        matched,_,_,_=keyword_match('精装交付含日立中央空调、霍尼韦尔新风、菲斯曼地暖、恩美特净水系统。',T1,self.taxonomy)
        ids={x['tag_id'] for x in matched}
        self.assertTrue({'VOC-0233','VOC-0234','VOC-0235','VOC-0236'}<=ids)

    def test_three_kitchen_devices(self):
        matched,_,_,_=keyword_match('厨房配有蒸烤一体机、双开门冰箱、洗碗机。',T2,self.taxonomy)
        self.assertTrue({'VOC-0263','VOC-0257','VOC-0260'}<={x['tag_id'] for x in matched})

    def test_object_mismatch_rejected(self):
        _,rejected,_,_=keyword_match('主卧还有两组衣柜赠送。',T2,self.taxonomy)
        self.assertIn('VOC-0316',{x['tag']['tag_id'] for x in rejected})

    def test_marketing_not_customer_need(self):
        matches,_,_,_=keyword_match('想了解价格，可以私信我预约看房。',T2,self.taxonomy)
        self.assertFalse(matches)

    def test_partial_matching_still_checks_residual(self):
        matches,_,_,uncovered=keyword_match('精装交付含中央空调，交通未来新增地铁站。',T1,self.taxonomy)
        self.assertTrue(matches);self.assertTrue(uncovered)

    def test_offline_no_api_or_final_summary(self):
        doc=make_doc(dict(self.posts[0],文章内容='厨房配有蒸烤一体机、双开门冰箱、洗碗机，精装配置省掉后期麻烦，主卧还有两组衣柜赠送。'))
        result=process_document(doc,self.taxonomy,'offline','http://invalid','invalid')
        self.assertFalse(result['calls']);self.assertTrue(result['slices'])
        self.assertTrue(all(x['人工验收状态']=='待人工验收' for x in result['slices']))
        self.assertTrue(all('离线' in x['复核原因'] for x in result['slices']))
        for row in result['slices']:
            self.assertEqual(doc['text'][row['证据起点']:row['证据终点']],row['原始摘录'])
            self.assertEqual(set(row),set(DELIVERY_FIELDS))


if __name__=='__main__':
    unittest.main(verbosity=2)
