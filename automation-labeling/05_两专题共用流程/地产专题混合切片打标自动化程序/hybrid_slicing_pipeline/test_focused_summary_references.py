import copy
import unittest
from focused_summary_references import catalog,select,evidence_only


class OpaqueEvidence(unittest.TestCase):
    def setUp(self):
        self.source='【父评论｜甲】安澜贵。朱房双子临快速路。【子评论1｜乙】我纠结保利熙瑞。'
        self.entries=catalog(self.source)
        self.response={'claims':[{'actor_quote':'甲','object_quote':'朱房双子','claim':'甲称朱房双子临快速路。',
                                  'evidence_keys':[self.entries[1]['source_key']],'confidence':.95}]}
    def test_body_after_caption_inherits_literal_speaker(self):
        self.assertEqual(['甲','甲','乙'],[e['speaker'] for e in self.entries])
        out,issues=select(self.response,self.entries)
        self.assertFalse(issues);self.assertEqual('朱房双子临快速路。',out[0]['verified_evidence'])

    def test_recovery_generation_cannot_inherit_selector_paraphrase(self):
        out,issues=select(self.response,self.entries)
        prompt=evidence_only(out)
        self.assertNotIn('claim',prompt[0])
        self.assertNotIn('object_quote',prompt[0])
        self.assertEqual(out[0]['verified_evidence'],prompt[0]['verified_evidence'])
    def test_child_ordinals_not_accepted(self):
        for keys in ([1],['1'],['SRC-0001']):
            r=copy.deepcopy(self.response);r['claims'][0]['evidence_keys']=keys
            self.assertIsNone(select(r,self.entries)[0])
    def test_actor_transfer_rejected(self):
        r=copy.deepcopy(self.response);r['claims'][0]['actor_quote']='乙'
        self.assertIsNone(select(r,self.entries)[0])
    def test_same_integer_index_different_actual_object_rejected(self):
        r=copy.deepcopy(self.response);r['claims'][0]['object_quote']='保利熙瑞'
        self.assertIsNone(select(r,self.entries)[0])
    def test_keys_are_stable_but_distinct_for_repeated_text(self):
        a=catalog('好。好。');self.assertNotEqual(a[0]['source_key'],a[1]['source_key'])
        self.assertEqual(a,catalog('好。好。'))
    def test_invalid_item_does_not_falsely_report_complete_selection(self):
        r=copy.deepcopy(self.response);r['claims'].append(dict(r['claims'][0],object_quote='不存在'))
        out,issues=select(r,self.entries);self.assertIsNone(out);self.assertTrue(issues)


if __name__=='__main__':unittest.main()
