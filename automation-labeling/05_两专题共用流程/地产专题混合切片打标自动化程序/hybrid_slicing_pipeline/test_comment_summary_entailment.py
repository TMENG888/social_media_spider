import copy
import unittest
import comment_summary_entailment as review


class EntailmentTests(unittest.TestCase):
    def setUp(self):
        self.source='【父评论｜甲】没坐过，如果二选一也许巴士稍好。'
        self.prose='甲表示未乘坐过，只倾向在两者中选巴士。'
        payload=review.payload(self.source,self.prose)
        key=payload['source_evidence_catalog'][0]['source_key']
        self.response={'checks':[{'prose_key':p['prose_key'],'status':'supported',
            'source_keys':[key],'object_binding_supported':True,'relation_supported':True,
            'modality_preserved':True,'qualifiers_preserved':True,'why':'未实测且相对倾向保留','confidence':.95}
            for p in payload['prose_catalog']],
            'coverage':{'captures_primary_points':True,'source_keys':[key],'why':'相对偏好保留','confidence':.95}}

    def test_all_required_dimensions_are_checked(self):
        self.assertTrue(review.verify(self.source,self.prose,self.response)[0])
        for key in ('object_binding_supported','relation_supported','modality_preserved','qualifiers_preserved'):
            for value in (False,None):
                response=copy.deepcopy(self.response);response['checks'][0][key]=value
                self.assertFalse(review.verify(self.source,self.prose,response)[0])

    def test_unknown_source_key_and_missing_prose_key_rejected(self):
        response=copy.deepcopy(self.response);response['checks'][0]['source_keys']=['SRC-unknown']
        self.assertFalse(review.verify(self.source,self.prose,response)[0])
        response=copy.deepcopy(self.response);response['checks']=[]
        self.assertFalse(review.verify(self.source,self.prose,response)[0])

    def test_counterexample_wins_over_high_confidence(self):
        response=copy.deepcopy(self.response);response['checks'][0].update(status='unsupported',confidence=.99)
        self.assertFalse(review.verify(self.source,self.prose,response)[0])


if __name__=='__main__':unittest.main()
