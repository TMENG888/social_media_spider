import copy
import unittest
from final_semantic_granularity_review import payload, protocol_errors, boundary_change_errors


class FinalGranularityTests(unittest.TestCase):
    def valid(self):
        return {'review':[{'unit_index':0,'verdict':'split','object':'项目','theme':'规划及不同配套主题','topic_kind':'mixed','why':'单片误合'}],
                'units':[{'start_quote':'全文开头','start_occurrence':1},
                         {'start_quote':'第二个独立主题','start_occurrence':1}]}

    def test_singleton_can_split(self):
        self.assertEqual(protocol_errors(self.valid(),1),[])

    def test_comments_never_enter(self):
        with self.assertRaises(ValueError): payload('评论',[],'评论')

    def test_source_kept_full(self):
        source='完整原文，包括不相关开场及结尾'
        self.assertEqual(payload(source,[{'excerpt':'原文'}])['source_text'],source)

    def test_no_mutation(self):
        before=[{'excerpt':'原文','meta':[]}];expected=copy.deepcopy(before)
        request=payload('原文',before);request['previous_partition'][0]['meta'].append(1)
        self.assertEqual(before,expected)

    def test_review_all_intervals_not_only_merged(self):
        self.assertTrue(protocol_errors(self.valid(),2))

    def test_duplicate_review_fails(self):
        x=self.valid();x['review']*=2
        self.assertTrue(protocol_errors(x,2))

    def test_boolean_is_not_index(self):
        x=self.valid();x['review'][0]['unit_index']=False
        self.assertTrue(protocol_errors(x,1))

    def test_unknown_verdict_fails(self):
        x=self.valid();x['review'][0]['verdict']='looks_fine'
        self.assertTrue(protocol_errors(x,1))

    def test_missing_concrete_explanation_fails(self):
        x=self.valid();x['review'][0]['object']=''
        self.assertTrue(protocol_errors(x,1))

    def test_missing_final_boundaries_fails(self):
        x=self.valid();x['units']=[]
        self.assertTrue(protocol_errors(x,1))

    def test_mixed_theme_cannot_be_keep(self):
        x=self.valid();x['review'][0]['verdict']='keep'
        self.assertTrue(protocol_errors(x,1))

    def test_macro_theme_is_not_valid_topic_kind(self):
        x=self.valid();x['review'][0]['topic_kind']='周边配套'
        self.assertTrue(protocol_errors(x,1))

    def test_occurrence_must_be_positive_integer(self):
        x=self.valid();x['units'][0]['start_occurrence']=0
        self.assertTrue(protocol_errors(x,1))

    def test_non_object_fails(self):
        self.assertTrue(protocol_errors(None,1))

    def test_split_claim_cannot_keep_old_boundary(self):
        self.assertTrue(boundary_change_errors([{'unit_index':0,'verdict':'split'}],['甲乙'],['甲乙']))

    def test_real_split_and_lossless(self):
        self.assertEqual(boundary_change_errors([{'unit_index':0,'verdict':'split'}],['甲乙'],['甲','乙']),[])

    def test_real_merge(self):
        self.assertEqual(boundary_change_errors([{'unit_index':0,'verdict':'merge'}],['甲','乙'],['甲乙']),[])

    def test_merge_claim_cannot_keep_old_boundary(self):
        self.assertTrue(boundary_change_errors([{'unit_index':0,'verdict':'merge'}],['甲','乙'],['甲','乙']))

    def test_mutation_or_reordering_rejected(self):
        self.assertTrue(boundary_change_errors([],['甲乙'],['乙甲']))


if __name__ == '__main__':unittest.main()
