import copy,unittest
import physical_scope_pass_v57 as p

class PhysicalScope(unittest.TestCase):
    def setUp(self):
        self.text='甲的庭园设环形步道。甲的室内会所设阅读区和瑜伽区。'
        self.plan={'units':[{'source_start_id':1,'source_end_id':1,'relevant':True}]}
        self.segments=[{'id':1,'start':0,'end':len(self.text),'text':self.text}]
        def scope(subject,ev,cat,quote=None):return {'from_target_start':quote is None,'start_quote':quote,'start_occurrence':1,
            'subject':subject,'subject_evidence':ev,'scope_category':cat,'scope_reason':subject,'relevant':True,'boundary_confidence':.95}
        self.raw={'scopes':[scope('甲庭园','环形步道','landscape'),scope('甲室内会所','阅读区和瑜伽区','clubhouse','甲的室内会所设阅读区和瑜伽区。')],'why':'实际从庭园转换为室内会所，设施列表完整。'}
    def test_literal_lossless_transition_and_multifacility_kept(self):
        out,seg,issues=p.apply_one(self.plan,self.segments,self.raw)
        self.assertFalse(issues);self.assertEqual(self.text,''.join(s['text'] for s in seg));self.assertEqual(2,len(out['units']))
        self.assertTrue(p.merge_issues(out,0,1,{'kind':'comparison'}))
    def test_same_root_multiple_facilities_can_remain_whole(self):
        text='同一会所设阅读区和瑜伽区。';raw=copy.deepcopy(self.raw);raw['scopes']=raw['scopes'][1:]
        raw['scopes'][0].update(from_target_start=True,start_quote=None)
        out,seg,issues=p.apply_one(self.plan,[dict(self.segments[0],text=text,end=len(text))],raw)
        self.assertFalse(issues);self.assertEqual(1,len(out['units']));self.assertFalse(p.merge_issues(out,0,0,{'kind':'comparison'}))
    def test_other_piece_quote_not_borrowed(self):
        raw=copy.deepcopy(self.raw);raw['scopes'][1]['subject_evidence']='环形步道'
        self.assertTrue(p.apply_one(self.plan,self.segments,raw)[2])
    def test_bad_anchor_score_or_missing_proof_rejected(self):
        for modify in ('anchor','score','proof'):
            raw=copy.deepcopy(self.raw)
            if modify=='anchor':raw['scopes'][1]['start_quote']='原文没有的分界'
            if modify=='score':raw['scopes'][1]['boundary_confidence']=.89
            if modify=='proof':del raw['scopes'][1]['subject_evidence']
            self.assertTrue(p.apply_one(self.plan,self.segments,raw)[2])

if __name__=='__main__':unittest.main()
