import copy
import unittest
from local_granularity_repair import apply


class LocalRepairTests(unittest.TestCase):
    def setup_case(self):
        plan={'units':[{'source_start_id':1,'source_end_id':1,'scope_reason':'多主题','relevant':True}]}
        segments=[{'id':1,'start':0,'end':6,'text':'规划交通教育'}]
        response={'repairs':[{'unit_index':0,'action':'split','why':'三个主题','units':[
            {'start_quote':word,'start_occurrence':1,'scope_reason':word,'relevant':True}
            for word in ('规划','交通','教育')]}]}
        return plan,segments,response

    def test_actual_model_boundaries_preserve_every_character(self):
        p,s,r=self.setup_case();out,segments,errors=apply(p,r,s,[0])
        self.assertEqual(errors,[]);self.assertEqual([x['text'] for x in segments],['规划','交通','教育'])
        self.assertEqual(len(out['units']),3)

    def test_target_start_reference_preserves_prefix_without_guessing_new_boundary(self):
        p,s,r=self.setup_case();r['repairs'][0]['units'][0]={'from_target_start':True,'scope_reason':'规划','relevant':True}
        out,segments,errors=apply(p,r,s,[0])
        self.assertFalse(errors)
        self.assertEqual([x['text'] for x in segments],['规划','交通','教育'])
        r['repairs'][0]['units'][1]['from_target_start']=True
        self.assertTrue(apply(p,r,s,[0])[2])

    def test_no_input_mutation(self):
        p,s,r=self.setup_case();original=copy.deepcopy((p,s,r));apply(p,r,s,[0])
        self.assertEqual((p,s,r),original)

    def test_unimplemented_split_rejected(self):
        p,s,r=self.setup_case();r['repairs'][0]['units']=r['repairs'][0]['units'][:1]
        self.assertTrue(apply(p,r,s,[0])[2])

    def test_missing_start_rejected(self):
        p,s,r=self.setup_case();r['repairs'][0]['units']=r['repairs'][0]['units'][1:]
        self.assertTrue(apply(p,r,s,[0])[2])

    def test_duplicate_or_reverse_boundaries_rejected(self):
        p,s,r=self.setup_case();r['repairs'][0]['units'][2]['start_quote']='交通'
        self.assertTrue(apply(p,r,s,[0])[2])

    def test_missing_or_duplicate_target_rejected(self):
        p,s,r=self.setup_case();self.assertTrue(apply(p,r,s,[0,1])[2])
        r['repairs']*=2;self.assertTrue(apply(p,r,s,[0])[2])

    def test_unknown_quote_not_fabricated(self):
        p,s,r=self.setup_case();r['repairs'][0]['units'][1]['start_quote']='医院'
        self.assertTrue(apply(p,r,s,[0])[2])

    def test_keep_can_correct_previous_false_split_verdict(self):
        p,s,r=self.setup_case();r={'repairs':[{'unit_index':0,'action':'keep','why':'单一对象','units':[]}]}
        self.assertFalse(apply(p,r,s,[0])[2])

    def test_long_anchor_prefix_does_not_borrow_other_interval(self):
        p,s,r=self.setup_case();text='引言'+('甲'*40)+'交通介绍'
        s=[{'id':1,'start':0,'end':len(text),'text':text}]
        r['repairs'][0]['units']=[
            {'start_quote':'引言','scope_reason':'引言','relevant':True},
            {'start_quote':('甲'*40)+'交通介绍'+'别的区间不存在的内容','scope_reason':'主题','relevant':True}]
        out,segments,errors=apply(p,r,s,[0])
        self.assertFalse(errors);self.assertEqual(''.join(x['text'] for x in segments),text)

    def test_first_anchor_still_needs_grounded_source(self):
        p,s,r=self.setup_case();r['repairs'][0]['units'][0]['start_quote']='捏造的片头'
        self.assertTrue(apply(p,r,s,[0])[2])

    def test_numbered_caption_prefix_is_preserved_not_removed(self):
        p,s,r=self.setup_case();text='03、周边配套规划交通教育'
        s=[{'id':1,'start':0,'end':len(text),'text':text}]
        out,segments,errors=apply(p,r,s,[0])
        self.assertFalse(errors);self.assertEqual(segments[0]['text'],'03、周边配套规划')

    def test_new_boundary_does_not_inherit_old_confidence(self):
        p,s,r=self.setup_case();p['units'][0]['confidence']={'boundary':.99}
        out,segments,errors=apply(p,r,s,[0])
        self.assertIsNone(out['units'][0]['confidence']['boundary'])


if __name__=='__main__':unittest.main()
