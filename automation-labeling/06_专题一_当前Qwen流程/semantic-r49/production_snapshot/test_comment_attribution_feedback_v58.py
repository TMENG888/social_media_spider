import unittest
import comment_attribution_feedback_v58 as v


class AttributionFeedback(unittest.TestCase):
    def test_failed_link_keys_retained_without_long_attribute_or_history(self):
        checks=[{'prose_key':'P1','accepted':False,'assertion_quote':'旧归属',
                 'issues':['跨轮次归属无据'],'raw_object_bindings':[{'object_quote':'南苑','object_source_key':'S1',
                 'attribute_source_key':'S2','attribute_quote':'长原文','history':['旧响应']}]}]
        out=v.compact_feedback(checks)
        self.assertEqual('S2',out[0]['failed_bindings'][0]['attribute_source_key'])
        self.assertNotIn('attribute_quote',out[0]['failed_bindings'][0])
        self.assertFalse(out[0]['accepted']);self.assertIn('长原文',checks[0]['raw_object_bindings'][0]['attribute_quote'])
    def test_success_is_not_misrepresented_as_failed_binding(self):
        self.assertEqual([],v.compact_feedback([{'prose_key':'P1','accepted':True,'raw_object_bindings':[{}]}]))
    def test_existing_qualification_and_semantic_gates_preserved(self):
        self.assertIs(v.verify,v.previous.verify)
        self.assertIn(v.previous.GENERATION_INSTRUCTION,v.GENERATION_INSTRUCTION)


if __name__=='__main__':unittest.main()
