import copy
import unittest
import post_split_scope_groups as grouping


class ScopeGroups(unittest.TestCase):
    def setUp(self):
        texts=['接下来讲洗手间防臭。','采用补水装置。','主持人说好的。','防臭纠正问答。','厨房烟道密封。']
        self.doc={'kind':'文章','topic':'全国地产设计产品力监测','text':''.join(texts)}
        self.segments=[];start=0
        for i,text in enumerate(texts,1):
            self.segments.append({'id':i,'start':start,'end':start+len(text),'text':text});start+=len(text)
        self.plan={'units':[{'source_start_id':i,'source_end_id':i,'relevant':i in (2,4,5),
                            'practice':'旧做法','summary':'旧摘要','labels':['旧标签'],'confidence':{'boundary':.95}}
                            for i in range(1,6)]}
        keys=[e['source_unit_key'] for e in grouping.catalog(self.doc,self.plan,self.segments)]
        self.response={'groups':[{'kind':'same_object','members':[
            {'source_unit_key':k,'role':role} for k,role in zip(keys[:4],('object_frame','facts','bridge','facts'))],
            'same_topic':True,'same_object':True,'object_scope':'single_solution',
            'object_description':'洗手间防臭方案','object_source_quotes':['洗手间防臭'],
            'why':'引导、装置与纠正问答连续承接，同一方案，中间互动没有新对象','confidence':.95},
            {'kind':'singleton','members':[{'source_unit_key':keys[4],'role':'facts'}],
             'why':'厨房烟道是不同对象','confidence':.95}]}

    def apply(self):return grouping.apply(self.doc,self.plan,self.segments,self.response)

    def test_object_frame_and_brief_bridge_kept_with_facts_losslessly(self):
        before=copy.deepcopy(self.plan);out,issues=self.apply()
        self.assertFalse(issues);self.assertEqual(2,len(out['units']))
        self.assertEqual(4,out['units'][0]['source_end_id']);self.assertEqual(before,self.plan)
        self.assertEqual(self.doc['text'],''.join(''.join(s['text'] for s in
            self.segments[u['source_start_id']-1:u['source_end_id']]) for u in out['units']))
        self.assertIsNone(out['units'][0]['practice']);self.assertIsNone(out['units'][0]['summary'])
        self.assertEqual([],out['units'][0]['labels']);self.assertEqual(5,out['units'][1]['source_start_id'])

    def test_missing_or_reordered_source_key_rejected(self):
        self.response['groups'][0]['members'].reverse()
        self.assertTrue(self.apply()[1])

    def test_irrelevant_fact_cannot_be_called_bridge_without_explicit_role(self):
        self.response['groups'][0]['members'][2]['role']='irrelevant'
        out,issues=self.apply();self.assertTrue(issues);self.assertEqual(self.plan,out)

    def test_general_project_overview_scope_cannot_merge(self):
        self.response['groups'][0]['object_scope']='project_overview'
        self.assertTrue(self.apply()[1])

    def test_future_object_quote_not_used_for_earlier_group(self):
        self.response['groups'][0]['object_source_quotes']=['厨房烟道']
        self.assertTrue(self.apply()[1])

    def test_low_confidence_keeps_original_partition(self):
        self.response['groups'][0]['confidence']=.89
        out,issues=self.apply();self.assertTrue(issues);self.assertEqual(self.plan,out)

    def test_comments_bypass_final_article_grouping(self):
        class NoCall:
            def call(self,*args):raise AssertionError('评论不得调用文章分组')
        out,audit,calls,issues=grouping.review(dict(self.doc,kind='评论'),self.plan,self.segments,NoCall())
        self.assertIs(out,self.plan);self.assertEqual([],calls)


if __name__=='__main__':unittest.main()
