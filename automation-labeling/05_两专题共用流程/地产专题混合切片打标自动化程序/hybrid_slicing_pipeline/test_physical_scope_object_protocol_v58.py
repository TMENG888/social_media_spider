import copy,unittest
import physical_scope_object_protocol_v58 as p
import test_physical_scope_pass_v57 as fixtures

class ObjectProof(unittest.TestCase):
    def setUp(self):
        f=fixtures.PhysicalScope();f.setUp();self.plan=f.plan;self.seg=f.segments;self.raw=copy.deepcopy(f.raw)
        for s in self.raw['scopes']:s['root_objects']=[{'subject':s['subject'],'quote':s['subject_evidence'],'category':s['scope_category'],'role':'facts'}]
    def test_separate_root_objects_and_whole_facility_preserved(self):
        out,seg,issues=p.apply_one(self.plan,self.seg,self.raw)
        self.assertFalse(issues);self.assertEqual(2,len(out['units']));self.assertEqual(self.seg[0]['text'],''.join(s['text'] for s in seg))
    def test_combined_scope_cannot_hide_different_root_facts(self):
        raw=copy.deepcopy(self.raw);raw['scopes']=raw['scopes'][:1]
        raw['scopes'][0]['root_objects']+=self.raw['scopes'][1]['root_objects']
        self.assertTrue(any('不同实际根对象' in x for x in p.apply_one(self.plan,self.seg,raw)[2]))
    def test_inconsistent_category_not_silently_rewritten(self):
        raw=copy.deepcopy(self.raw);raw['scopes'][0]['scope_category']='clubhouse'
        self.assertTrue(any('类别矛盾' in x for x in p.apply_one(self.plan,self.seg,raw)[2]))
    def test_root_quote_cannot_borrow_other_slice(self):
        raw=copy.deepcopy(self.raw);raw['scopes'][1]['root_objects'][0]['quote']='环形步道'
        self.assertTrue(any('不在本片' in x for x in p.apply_one(self.plan,self.seg,raw)[2]))
    def test_review_receives_full_article_and_preserves_all_source_offsets(self):
        class Runner:
            def __init__(self,response):self.response=response;self.requests=[]
            def call(self,system,payload,doc,phase,**kwargs):
                self.requests.append((payload,kwargs));return copy.deepcopy(self.response),{'status':'success'}
        runner=Runner(self.raw);text=self.seg[0]['text']
        out,spans,audit,calls=p.review({'kind':'文章','topic':'北京臻澐项目口碑','text':text},self.plan,self.seg,runner)
        self.assertEqual(text,runner.requests[0][0]['source_text']);self.assertEqual(text,runner.requests[0][0]['target_text'])
        self.assertEqual(2,len(out['units']));self.assertEqual(1,len(calls));self.assertTrue(audit[0]['checks'][0]['accepted'])
        self.assertEqual(0,spans[0]['start']);self.assertEqual(len(text),spans[-1]['end']);self.assertEqual(spans[0]['end'],spans[1]['start'])
        self.assertEqual(text,''.join(s['text'] for s in spans))
        self.assertIn('root_objects',audit[0]['checks'][0]['raw_root_object_response']['scopes'][0])
    def test_comments_remain_whole_without_calling_scope_model(self):
        class Runner:
            def call(self,*args,**kwargs):raise AssertionError('评论不得执行范围切分')
        out,spans,audit,calls=p.review({'kind':'评论','topic':'北京臻澐项目口碑'},self.plan,self.seg,Runner())
        self.assertEqual(self.plan,out);self.assertEqual(self.seg,spans);self.assertFalse(calls)

if __name__=='__main__':unittest.main()
