import copy
import unittest
import article_identity_metadata_review as review


class ArticleMetadata(unittest.TestCase):
    def setUp(self):
        self.source='央企中海开发中海江岸北京，项目位于北京。住宅面积210-370平方米。'
        self.entries=review.catalog(self.source)
        self.segments=[{'start':0,'end':len(self.source)}]
        self.units=[{'source_start_id':1,'source_end_id':1,'brand':'北京某地产有限公司'}]
        key=self.entries[0]['source_key']
        self.response={'metadata':[{'unit_index':0,**{f:{'value':v,'source_keys':[key] if v else [],
            'why':'全文明确开发品牌、案名及所在地' if v else '未明确业务字典法律主体','confidence':.95}
            for f,v in zip(review.FIELDS,('中海',None,'中海江岸北京','北京'))}}]}

    def apply(self):return review.apply(self.units,self.segments,self.response,self.entries,{'entities':[]})

    def test_single_project_identity_without_borrowing_configuration(self):
        original=copy.deepcopy(self.units);out,issues=self.apply()
        self.assertFalse(issues);self.assertEqual('中海',out[0]['brand'])
        self.assertEqual('中海江岸北京',out[0]['project_name']);self.assertEqual('北京',out[0]['city'])
        self.assertIsNone(out[0]['entity']);self.assertEqual(original,self.units)
        self.assertNotIn('labels',out[0]);self.assertNotIn('practice',out[0])

    def test_company_is_not_developer_brand(self):
        self.response['metadata'][0]['brand']['value']='北京某地产有限公司'
        self.assertTrue(self.apply()[1])

    def test_future_identity_not_used(self):
        self.segments[0]['end']=5
        self.assertTrue(self.apply()[1])

    def test_missing_confidence_not_defaulted(self):
        del self.response['metadata'][0]['project_name']['confidence']
        self.assertTrue(self.apply()[1])

    def test_wrong_keys_cannot_create_identity(self):
        self.response['metadata'][0]['city']['source_keys']=['SRC-UNKNOWN']
        self.assertTrue(self.apply()[1])

    def test_legal_entity_not_in_dictionary_not_granted(self):
        self.response['metadata'][0]['entity'].update(value='中海',source_keys=[self.entries[0]['source_key']])
        out,issues=self.apply();self.assertTrue(issues);self.assertNotEqual('中海',out[0].get('entity'))


if __name__=='__main__':unittest.main()
