import copy
import unittest
import branch_added_condition_review as review


class BranchRecheck(unittest.TestCase):
    def setUp(self):
        self.index={'D1':{'instruction':'记录洗手间地漏配置。例：如明确提供品牌、型号、规格或配置。',
                         'emphasis':'地漏配置','tag_id':'SYNTHETIC-D1','l1':'产品','l2':'卫浴'}}
        self.case={'child':{'excerpt':'洗手间地漏自动补水。'},'context':'','document':{'record_id':'SYNTHETIC'}}
        self.audit={'response':{'decisions':[{'choice_key':'D1','status':'unsupported',
            'why':'原文只描述自动补水配置，未提供品牌型号'}]}}
        self.response={'decisions':[{'choice_key':'D1','status':'supported','direct_quote':'洗手间地漏自动补水。',
            'object_quote':'洗手间','why':'明示对象和自动补水配置，定义接受配置作为备选条件','confidence':.95}]}

    def test_recovers_lead_not_automatic_tag(self):
        self.assertEqual({'D1'},set(review.leads(self.audit,self.index)))
        self.assertFalse(review.validate(self.response,{'D1'},self.case,self.index)[1])
        self.assertEqual('unsupported',self.audit['response']['decisions'][0]['status'])

    def test_missing_configuration_is_not_added_brand_condition(self):
        self.audit['response']['decisions'][0]['why']='未提供品牌型号、规格或配置'
        self.assertFalse(review.leads(self.audit,self.index))

    def test_illegal_extra_key_rejected(self):
        self.response['decisions'].append(dict(self.response['decisions'][0],choice_key='D-ILLEGAL'))
        self.assertTrue(review.validate(self.response,{'D1'},self.case,self.index)[1])

    def test_fabricated_evidence_not_recovered(self):
        self.response['decisions'][0]['direct_quote']='阳台地漏自动补水。'
        self.assertTrue(review.validate(self.response,{'D1'},self.case,self.index)[1])

    def test_low_confidence_not_defaulted(self):
        self.response['decisions'][0]['confidence']=.6
        self.assertTrue(review.validate(self.response,{'D1'},self.case,self.index)[1])

    def test_duplicate_decision_rejected(self):
        self.response['decisions'].append(copy.deepcopy(self.response['decisions'][0]))
        self.assertTrue(review.validate(self.response,{'D1'},self.case,self.index)[1])

    def runner(self,responses):
        class Runner:
            def __init__(self):self.calls=[]
            def call(inner,system,payload,doc,phase):
                inner.calls.append((system,payload))
                return copy.deepcopy(responses[min(len(inner.calls)-1,len(responses)-1)]),{'status':'success'}
        return Runner()

    def test_bounded_recheck_keeps_original_and_only_returns_candidate(self):
        original=copy.deepcopy(self.audit);runner=self.runner([self.response])
        out,calls,issues=review.review(self.audit,self.case,self.index,runner)
        self.assertFalse(issues);self.assertEqual(original,self.audit)
        self.assertEqual(1,len(calls));self.assertEqual(1,len(out['supported']))
        self.assertEqual('unsupported',out['added_condition_review']['original_response']['decisions'][0]['status'])
        self.assertNotIn('验收状态',out)

    def test_failed_recheck_never_overwrites_original_decision(self):
        original=copy.deepcopy(self.audit);runner=self.runner([{'decisions':[]}])
        out,calls,issues=review.review(self.audit,self.case,self.index,runner)
        self.assertEqual(2,len(calls));self.assertTrue(issues)
        self.assertEqual(original['response'],out['response']);self.assertFalse(out.get('supported'))

    def test_repeated_added_requirement_stays_ambiguous_not_granted(self):
        denied=copy.deepcopy(self.response)
        denied['decisions'][0].update(status='unsupported',why='原文只描述自动补水配置，未提供品牌型号')
        out,calls,issues=review.review(self.audit,self.case,self.index,self.runner([denied]))
        self.assertFalse(issues);self.assertFalse(out['supported'])
        self.assertEqual('ambiguous',out['response']['decisions'][0]['status'])


if __name__=='__main__':unittest.main()
