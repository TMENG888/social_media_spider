import unittest
from unittest.mock import patch
import full_source_inventory_partition_v54 as v

class FactualContext(unittest.TestCase):
    def test_underlying_runner_preserved_and_context_not_authority(self):
        class Runner:
            supports_response_schema=True
            def call(self,system,payload,doc,phase,**kwargs):
                self.request=(system,payload,doc,phase,kwargs)
                return {'approved':False},{'status':'success'}
        runner=Runner();proxy=v.InventoryRunner(runner,{'members':{'A':{'relation':'correction'}}})
        self.assertTrue(proxy.supports_response_schema)
        response,metric=proxy.call('independent',{'source_text':'原文'}, {},'audit',response_schema={'type':'object'})
        self.assertFalse(response['approved']);self.assertEqual({'type':'object'},runner.request[-1]['response_schema'])
        self.assertIn('不是事实权威',runner.request[0]);self.assertEqual('原文',runner.request[1]['source_text'])
    def test_inventory_failure_not_silently_accepted(self):
        plan={'units':[{},{}]}
        with patch.object(v.previous.ranges.previous.previous.previous.grouping,'catalog',return_value=[]),\
             patch.object(v.inventory,'review',return_value=(None,[],[],['目录失败'])),\
             patch.object(v.previous,'review') as grouping:
            out,audit,calls,errors=v.review({'kind':'文章'},plan,[],object())
        grouping.assert_not_called();self.assertEqual(plan,out);self.assertTrue(errors)
    def test_comment_never_sliced(self):
        with patch.object(v.inventory,'review') as inventory:
            plan={'units':[{},{}]};self.assertEqual((plan,[],[],[]),v.review({'kind':'评论'},plan,[],object()))
        inventory.assert_not_called()

if __name__=='__main__':unittest.main()
