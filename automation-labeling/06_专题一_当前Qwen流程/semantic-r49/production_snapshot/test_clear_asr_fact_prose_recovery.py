import unittest
from unittest.mock import Mock
import clear_asr_fact_prose_recovery as recovery


class ClearAsrRecovery(unittest.TestCase):
    def setUp(self):
        self.source='采用环保材料，名称识别不清。厨房窗户较大。'
        self.entries=recovery.review.payload(self.source,'')['source_evidence_catalog']
        self.response={'facts':[{'source_key':self.entries[0]['source_key'],'quote':'采用环保材料'}]}

    def test_literal_facts_only(self):
        facts,errors=recovery.select(self.response,self.entries)
        self.assertFalse(errors);self.assertEqual('采用环保材料',facts[0]['quote'])

    def test_fabricated_material_not_accepted(self):
        self.response['facts'][0]['quote']='采用竹材'
        self.assertTrue(recovery.select(self.response,self.entries)[1])

    def test_unknown_key_or_duplicate_not_accepted(self):
        self.response['facts'].append(dict(self.response['facts'][0]))
        self.assertTrue(recovery.select(self.response,self.entries)[1])

    def test_no_clear_facts_does_not_copy_source(self):
        runner=Mock();runner.call.return_value=({'facts':[]},{'status':'success'})
        out,audit,calls,errors=recovery.recover(self.source,'',{},runner,lambda x:True)
        self.assertIsNone(out);self.assertTrue(errors);self.assertEqual(1,len(calls))

    def test_generation_never_success_without_independent_audit(self):
        runner=Mock();runner.call.side_effect=[(self.response,{'status':'success'}),
            ({'checks':[{'fact_index':0,'clear_product_fact':True,'why':'环保材料配置清楚','confidence':.95}]},{'status':'success'}),
            ({'practice':'转录称采用环保材料。','supported':True,'confidence':.99},{'status':'success'}),
            ({'checks':[]},{'status':'success'})]
        out,audit,calls,errors=recovery.recover(self.source,'',{},runner,lambda x:bool(x))
        self.assertIsNone(out);self.assertTrue(errors);self.assertEqual(4,len(calls))
        self.assertNotIn('previous_prose',runner.call.call_args_list[2].args[1])
        self.assertNotIn('source_text',runner.call.call_args_list[2].args[1])

    def test_clarity_filter_does_not_promote_uncertain_or_duplicate_indices(self):
        self.assertIsNone(recovery.clear_facts({'checks':[{'fact_index':0,'clear_product_fact':True,'why':'不确定','confidence':.89}]},self.response['facts'])[0])
        self.assertIsNone(recovery.clear_facts({'checks':[]},self.response['facts'])[0])


if __name__=='__main__':unittest.main()
