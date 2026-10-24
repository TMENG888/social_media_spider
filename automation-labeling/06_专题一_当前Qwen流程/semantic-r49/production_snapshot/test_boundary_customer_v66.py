import unittest
from unittest.mock import patch
import delivery_v66 as v


class BoundaryAndCustomerTests(unittest.TestCase):
    def visible(self):return v.current.current.current.current.current.current.visible

    def test_full_source_retained_but_leaf_dictionary_not_boundary_prompt(self):
        request={'source_text':'甲完整对象全文','source_catalog':[{'source_key':'K1'}],
                 'all_applicable_labels':[{'choice_key':'D1'}]}
        with patch.object(self.visible(),'review',return_value=(None,[],[],[])) as call:
            v.boundary_call('完整读取原文和当前专题标签定义',request,{}, {},'v11.65',None)
        actual=call.call_args.args[1]
        self.assertEqual(actual['source_text'],request['source_text'])
        self.assertNotIn('all_applicable_labels',actual)
        self.assertIn('all_applicable_labels',request)
        self.assertEqual(actual['first_source_key'],'K1')

    def test_non_customer_label_not_filtered_by_customer_stage(self):
        with patch.object(v,'_binding',return_value=(True,[],[],[])), \
             patch.object(self.visible(),'review') as extra:
            self.assertTrue(v.binding_review('配置',{'l1':'产品'},'',{},None)[0])
        extra.assert_not_called()

    def test_initially_rejected_label_not_pressure_retried(self):
        with patch.object(v,'_binding',return_value=(False,[],[],['已有拒绝'])), \
             patch.object(self.visible(),'review') as extra:
            self.assertFalse(v.binding_review('营销',{'l1':'客户'},'',{},None)[0])
        extra.assert_not_called()


if __name__=='__main__':unittest.main()
