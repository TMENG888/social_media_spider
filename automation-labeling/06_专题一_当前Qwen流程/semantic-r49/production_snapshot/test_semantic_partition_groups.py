import unittest
from semantic_partition_groups import apply_groups


class AdjacentSemanticGroups(unittest.TestCase):
    def setUp(self):
        self.segments=[{'text':'厨房止逆阀。'},{'text':'卫生间设置存水弯。'},{'text':'第二点地漏补水。'}]
        self.plan={'units':[{'source_start_id':i+1,'source_end_id':i+1,'relevant':True,
            'scope_reason':'配置','labels':[{'old':i}],'summary':'旧摘要','confidence':{'boundary':.95}} for i in range(3)]}
        self.response={'groups':[{'unit_indices':[0]}, {'unit_indices':[1,2],
            'object_quote':'卫生间','why':'同一完整卫生间防反味方案','confidence':.95,
            'same_object':True,'same_topic':True,'object_scope':'single_solution',
            'object_description':'卫生间防反味施工方案'}]}

    def test_contiguous_same_object_merge_preserves_source_and_regenerates_labels(self):
        output,issues=apply_groups(self.plan,self.response,self.segments)
        self.assertEqual([],issues)
        self.assertEqual(2,len(output['units']))
        merged=output['units'][1]
        self.assertEqual((2,3),(merged['source_start_id'],merged['source_end_id']))
        self.assertEqual([],merged['labels']);self.assertIsNone(merged['summary'])
        self.assertEqual(3,len(self.plan['units']))

    def test_noncontiguous_or_incomplete_or_duplicate_groups_do_not_guess(self):
        for groups in ([[0],[2,1]],[[0],[1]],[[0],[1,1],[2]]):
            response={'groups':[dict(unit_indices=g) for g in groups]}
            output,issues=apply_groups(self.plan,response,self.segments)
            self.assertTrue(issues);self.assertEqual(self.plan,output)

    def test_unlocated_or_low_confidence_object_does_not_merge(self):
        for patch in ({'object_quote':'不存在'}, {'confidence':.89}, {'confidence':True}, {'why':''}):
            response={'groups':[{'unit_indices':[0]},dict(self.response['groups'][1],**patch)]}
            self.assertTrue(apply_groups(self.plan,response,self.segments)[1])

    def test_different_project_or_scope_not_chosen_by_first_unit(self):
        self.plan['units'][1]['project_name']='甲项目'
        self.plan['units'][2]['project_name']='乙项目'
        self.assertTrue(apply_groups(self.plan,self.response,self.segments)[1])

    def test_object_evidence_id_backfills_actual_original_context(self):
        response={'groups':[{'unit_indices':[0]},dict(self.response['groups'][1],object_unit_index=1,object_quote='模型改写') ]}
        output,issues=apply_groups(self.plan,response,self.segments)
        self.assertEqual([],issues)
        self.assertEqual(self.segments[1]['text'],output['units'][1]['object_quote'])

    def test_object_evidence_id_not_bool_or_arbitrarily_far(self):
        for value in (True,'1',3,-1):
            response={'groups':[{'unit_indices':[0]},dict(self.response['groups'][1],object_unit_index=value)]}
            self.assertTrue(apply_groups(self.plan,response,self.segments)[1])
    def test_same_project_overview_cannot_merge_distinct_topics(self):
        response={'groups':[{'unit_indices':[0]},dict(self.response['groups'][1],
            object_scope='same_project',object_description='同项目全面介绍')]}
        output,issues=apply_groups(self.plan,response,self.segments)
        self.assertTrue(issues);self.assertEqual(self.plan,output)


if __name__=='__main__':unittest.main()
