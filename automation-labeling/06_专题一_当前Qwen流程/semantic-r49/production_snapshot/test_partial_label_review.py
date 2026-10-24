import unittest
from unittest.mock import Mock, patch
import delivery_v11 as v
from test_delivery_v4 import fixture, TAG


class PartialLabelReview(unittest.TestCase):
    def test_industry_assumption_reaches_independent_adjudication(self):
        checks=[{'choice_key':'D0211','status':'supported','direct_quote':'南向四面宽',
            'why':'南向四面宽通常包含主卧朝南'}]
        self.assertEqual(['D0211'],v.check_disputes(checks,{'D0211':{}},'南向四面宽',''))

    def test_missing_other_check_does_not_erase_supported_label(self):
        doc, unit, _ = fixture(topic=v.p.base.T1)
        unit.update(source_start_id=1, source_end_id=1, labels=[])
        audit={'calls':[], 'issues':[], 'expected_keys':['D0234','D9999'], 'supported':[],
            'response':{'decisions':[{'choice_key':k,'status':'ambiguous','why':'需独立核验'} for k in ['D0234','D9999']]}}
        check={'choice_key':'D0234','status':'supported','why':'原文明确配置中央空调',
            'direct_quote':'中央空调','confidence':.95}
        review={'checks':[check], 'practice':'住宅精装配置中央空调设备。',
            'prose_supported':True,'prose_confidence':.95,'confidence':.95,'issues':[]}
        runner=Mock();runner.call.return_value=(review,{'status':'success'})
        with patch.object(v.branch,'audit',return_value=audit), patch.object(v.p.v,'registry',return_value={'D0234':TAG,'D9999':TAG}), \
             patch.object(v.p.v,'catalogue',return_value=[{'choice_key':k} for k in ['D0234','D9999']]):
            out, report, _=v.check_unit(doc,unit,0,[{'text':doc['text']}],[TAG],runner)
        self.assertEqual(['D0234'],[t['choice_key'] for t in out['labels']])
        self.assertFalse(out['self_check']['pass'])
        self.assertTrue(any(a['choice_key']=='D9999' for a in report['ambiguous']))


if __name__=='__main__':unittest.main()
