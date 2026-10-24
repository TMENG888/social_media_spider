import unittest
from focused_summary_evidence import select
from label_evidence_reference import evidence_catalog


class FocusedEvidence(unittest.TestCase):
    def response(self):
        return {'claims':[{'actor_quote':'甲','object_quote':'保利熙瑞','claim':'甲觉得保利熙瑞贵。','evidence_ids':[1],'confidence':.95}]}
    def test_location_is_not_semantic_accuracy_claim(self):
        out=select(self.response(),evidence_catalog('【父评论｜甲】保利熙瑞贵。'))
        self.assertEqual('【父评论｜甲】保利熙瑞贵。',out[0]['verified_evidence'])
    def test_actor_and_object_must_exist_in_selected_evidence(self):
        for field,value in [('actor_quote','乙'),('object_quote','海晏')]:
            r=self.response();r['claims'][0][field]=value
            self.assertIsNone(select(r,evidence_catalog('【父评论｜甲】保利熙瑞贵。')))
    def test_bad_reference_no_silent_recovery(self):
        for ids in ([],[2],['1'],[1,1]):
            r=self.response();r['claims'][0]['evidence_ids']=ids
            self.assertIsNone(select(r,evidence_catalog('【父评论｜甲】保利熙瑞贵。')))
    def test_missing_and_overlong_claim_list(self):
        self.assertIsNone(select({},[]))
        r=self.response();r['claims']*=6
        self.assertIsNone(select(r,evidence_catalog('【父评论｜甲】保利熙瑞贵。')))


if __name__=='__main__':unittest.main()
