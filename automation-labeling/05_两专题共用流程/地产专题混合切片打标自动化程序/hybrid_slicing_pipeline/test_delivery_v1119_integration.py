"""Bounded integration recovery; not a semantic accuracy benchmark."""
import unittest
from unittest.mock import Mock
import delivery_v11 as v


class Recovery(unittest.TestCase):
    def scope(self, final):
        doc={'kind':'文章','topic':v.p.base.T1,'text':'卫生间存水弯水封大于50毫米'}
        unit={'source_start_id':1,'source_end_id':1,'scope_reason':'产品工艺','relevant':True}
        runner=Mock()
        runner.call.side_effect=[
            ({'relevant':False,'why':'误判无关','scope_evidence_id':1,
              'confidence':.95,'content_kind':'irrelevant'},{'status':'success'}),
            ({'exclude':False,'why':'相关但协议漏证据','evidence_ids':[1],
              'confidence':.95},{'status':'success'}),
            (final,{'status':'success'})]
        result=v.check_exclusion(doc,unit,[{'text':doc['text']}],runner)
        self.assertEqual(3,runner.call.call_count)
        self.assertIn('countercheck_recovery_call',result[3])
        return result

    def test_positive_fact_recovers_without_quarantine(self):
        result=self.scope({'exclude':False,'why':'住宅排水工艺','positive_facts':[
            {'kind':'product_fact','fact':'水封大于50毫米','evidence_ids':[1],
             'why':'明确存水弯工艺参数','confidence':.95}]})
        self.assertFalse(result[0]);self.assertNotIn('_scope_unresolved',result[1])

    def test_failed_recovery_stops_and_preserves_uncertainty(self):
        result=self.scope({'exclude':None,'positive_facts':[]})
        self.assertFalse(result[0]);self.assertTrue(result[1]['_scope_unresolved'])

    def test_failed_prose_not_copied_and_calls_bounded(self):
        runner=Mock();runner.call.return_value=({'supported':False},{'status':'success'})
        unit={'summary':None,'labels':[]}
        result=v.independent_prose_review({'topic':v.p.base.T2},unit,'交通是短板',None,runner)
        self.assertIsNone(result[0]['summary']);self.assertTrue(result[3])
        self.assertEqual(1,runner.call.call_count)

    def test_uncertain_invitation_requires_actual_fact_countercheck(self):
        text='欢迎留言或来工法样板间参观。'
        doc={'kind':'文章','topic':v.p.base.T1,'text':text}
        unit={'source_start_id':1,'source_end_id':1,'scope_reason':'结尾邀约','relevant':True}
        runner=Mock();runner.call.side_effect=[
            ({'relevant':True,'why':'纯邀约但谨慎保留','scope_evidence_id':1,
              'confidence':.95,'content_kind':'uncertain'},{'status':'success'}),
            ({'exclude':True,'why':'没有产品配置事实，只有参观邀约',
              'evidence_ids':[1],'positive_facts':[],'confidence':.95},{'status':'success'})]
        result=v.check_exclusion(doc,unit,[{'text':text}],runner)
        self.assertTrue(result[0])
        self.assertEqual(2,runner.call.call_count)

    def test_prose_repair_explicitly_requests_new_text_not_old_verdict(self):
        runner=Mock();runner.call.return_value=({'supported':False},{'status':'success'})
        v.independent_prose_review({'topic':v.p.base.T2},{'summary':None,'labels':[]},
                                  '下雪了还会用喷气发动机吹雪',None,runner)
        self.assertIn('supported针对新生成文案',runner.call.call_args.args[0])


if __name__=='__main__':unittest.main()
