import unittest
from opinion_expression_review import verify, verified_summary
from label_evidence_reference import evidence_catalog


class OpinionReview(unittest.TestCase):
    def test_summary_protocol_not_grounding_claim(self):
        response={'summary':'评论者认为噪音很困扰。','summary_supported':True,'summary_confidence':.95}
        self.assertEqual(response['summary'],verified_summary(response,'噪音令人害怕。'))
        for confidence in (True,None,.89):
            self.assertIsNone(verified_summary(dict(response,summary_confidence=confidence),'噪音令人害怕。'))
        self.assertIsNone(verified_summary(dict(response,summary='字'*81),'原文'))
        self.assertIsNone(verified_summary(dict(response,summary='字'*50),'字'*50))
        self.assertEqual('不错',verified_summary(dict(response,summary='不错'),'不错'))
    def response(self):
        return {'expression_checks':[{'value':'负向评价','evidence_ids':[1],'why':'明确害怕','confidence':.95}],
                'emotion_checks':[{'value':'负向','evidence_ids':[1],'why':'明确害怕','confidence':.95}]}
    def test_valid_grounded_categories(self):
        out,issues=verify(self.response(),evidence_catalog('噪音令人害怕。'))
        self.assertFalse(issues);self.assertEqual(['负向'],out['emotions'])
    def test_missing_or_wrong_enum_not_silent_default(self):
        r=self.response();r['emotion_checks'][0]['value']='negative'
        self.assertIsNone(verify(r,evidence_catalog('很吵。'))[0])
        self.assertIsNone(verify({},evidence_catalog('很吵。'))[0])
    def test_low_confidence_and_invalid_reference_rejected(self):
        for value in (.89,None,True):
            r=self.response();r['emotion_checks'][0]['confidence']=value
            self.assertIsNone(verify(r,evidence_catalog('很吵。'))[0])
        r=self.response();r['emotion_checks'][0]['evidence_ids']=[2]
        self.assertIsNone(verify(r,evidence_catalog('很吵。'))[0])
    def test_multiple_speakers_opposing_attitudes_supported(self):
        r=self.response();r['emotion_checks'].append({'value':'正向','evidence_ids':[2],'why':'另一人说不错','confidence':.95})
        self.assertEqual(['负向','正向'],verify(r,evidence_catalog('很吵。【子评论1】不错。'))[0]['emotions'])


if __name__=='__main__':unittest.main()
