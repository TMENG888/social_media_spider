import copy
import unittest
from source_bound_continuity_review import review


class Runner:
    def __init__(self,callback):self.callback=callback;self.requests=[]
    def call(self,system,payload,doc,phase):
        self.requests.append(copy.deepcopy(payload))
        return self.callback(payload,phase),{'status':'success'}


class SourceBoundReviewTests(unittest.TestCase):
    doc={'kind':'文章','topic':'北京臻澐项目口碑','text':'户型层高3.4米。设备后净高3米。联系方式。'}
    excerpts=['户型层高3.4米。','设备后净高3米。','联系方式。']
    plan={'units':[{'source_start_id':i+1,'source_end_id':i+1,'relevant':i<2,
                    'labels':[],'confidence':{}} for i in range(3)]}
    def response(self,payload,merge=True):
        return {'edges':[{'edge_key':e['edge_key'],'decision':'same_object' if merge else 'keep',
            'theme':'floorplan' if merge else None,'objects':'同一户型参数及解释' if merge else None,
            'why':'核对当前左右文本','confidence':.95} for e in payload['edge_catalog']]}
    def test_bad_contact_merge_only_rechecks_bad_edge(self):
        def callback(payload,phase):return self.response(payload,merge='恢复' not in phase)
        runner=Runner(callback)
        out,audit,calls,issues=review(self.doc,self.plan,self.excerpts,runner)
        self.assertFalse(issues);self.assertEqual(2,len(out['units']))
        self.assertEqual(1,len(runner.requests[1]['edge_catalog']))
        self.assertEqual(2,out['units'][0]['source_end_id'])
    def test_missing_decision_is_recovered_without_replacing_first_valid_decision(self):
        def callback(payload,phase):
            r=self.response(payload,merge='恢复' not in phase)
            if '恢复' not in phase:r['edges']=r['edges'][:1]
            return r
        runner=Runner(callback)
        self.assertFalse(review(self.doc,self.plan,self.excerpts,runner)[3])
        self.assertEqual(1,len(runner.requests[1]['edge_catalog']))
    def test_unresolved_keys_do_not_default_to_keep_or_merge(self):
        runner=Runner(lambda p,phase:{'edges':[]})
        out,_,calls,issues=review(self.doc,self.plan,self.excerpts,runner)
        self.assertFalse(issues);self.assertEqual(3,len(out['units']));self.assertEqual(2,len(calls))
        self.assertTrue(all(u.get('uncertainties') for u in out['units']))
        self.assertFalse(out['source_bound_continuity_review_audit'][-1]['verification_complete'])
    def test_unresolved_contact_does_not_cancel_verified_layer_merge(self):
        def callback(payload,phase):
            response=self.response(payload)
            # First round confirms only the parameter/explanation boundary;
            # recovery for the contact boundary stays unresolved.
            if '恢复' in phase:response['edges']=[]
            else:response['edges']=response['edges'][:1]
            return response
        out,_,_,issues=review(self.doc,self.plan,self.excerpts,Runner(callback))
        self.assertFalse(issues);self.assertEqual(2,len(out['units']))
        self.assertEqual(2,out['units'][0]['source_end_id'])
        self.assertTrue(out['units'][1]['uncertainties'])
    def test_every_small_batch_still_receives_full_article(self):
        excerpts=[str(i)+'独立主题。' for i in range(8)]
        plan={'units':[{'source_start_id':i+1,'source_end_id':i+1,'relevant':True} for i in range(8)]}
        runner=Runner(lambda p,phase:self.response(p,False))
        out,_,calls,issues=review(self.doc,plan,excerpts,runner)
        self.assertFalse(issues);self.assertEqual(2,len(calls))
        self.assertTrue(all(p['source_text']==self.doc['text'] and len(p['edge_catalog'])<=5 for p in runner.requests))
    def test_comment_cannot_be_sliced_by_this_stage(self):
        runner=Runner(lambda p,phase:None)
        self.assertEqual([],review(dict(self.doc,kind='评论'),self.plan,self.excerpts,runner)[2])
        self.assertFalse(runner.requests)


if __name__=='__main__':unittest.main()
