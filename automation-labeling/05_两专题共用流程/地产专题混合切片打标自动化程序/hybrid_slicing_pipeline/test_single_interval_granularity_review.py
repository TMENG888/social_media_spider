import copy
import unittest
from single_interval_granularity_review import review


class Runner:
    def __init__(self,response):self.response=response;self.requests=[]
    def call(self,system,payload,doc,phase):
        self.requests.append(copy.deepcopy(payload))
        return copy.deepcopy(self.response),{'status':'success'}


class SingleInterval(unittest.TestCase):
    text='会所由设计团队打造。项目距离江岸五百米。'
    doc={'kind':'文章','topic':'全国地产设计产品力监测','text':text}
    segments=[{'id':1,'start':0,'end':len(text),'text':text}]
    plan={'units':[{'source_start_id':1,'source_end_id':1,'relevant':True,'confidence':{}}]}
    def test_model_split_exact_boundaries_and_full_source(self):
        runner=Runner({'repairs':[{'unit_index':0,'action':'split','why':'会所和外部区位不同主题',
            'units':[{'start_quote':'会所由设计团队打造。','scope_reason':'会所','relevant':True,'boundary_confidence':.95},
                     {'start_quote':'项目距离江岸五百米。','scope_reason':'外部区位','relevant':True,'boundary_confidence':.95}]}]})
        out,segments,_,_=review(self.doc,self.plan,self.segments,runner)
        self.assertEqual(2,len(out['units']))
        self.assertEqual(self.text,''.join(s['text'] for s in segments))
        self.assertEqual(self.text,runner.requests[0]['source_text'])
        self.assertEqual(0,runner.requests[0]['repair_targets'][0]['unit_index'])
    def test_bad_quote_retains_source_with_uncertainty(self):
        runner=Runner({'repairs':[{'unit_index':0,'action':'split','why':'拆分','units':[
            {'start_quote':'会所由设计团队打造。','scope_reason':'会所','relevant':True},
            {'start_quote':'伪造引文','scope_reason':'区位','relevant':True}]}]})
        out,segments,_,calls=review(self.doc,self.plan,self.segments,runner)
        self.assertEqual(self.segments,segments);self.assertEqual(1,len(out['units']))
        self.assertTrue(out['units'][0]['uncertainties']);self.assertEqual(2,len(calls))
    def test_comment_is_never_split(self):
        runner=Runner(None)
        out,segments,_,calls=review(dict(self.doc,kind='评论'),self.plan,self.segments,runner)
        self.assertEqual(self.plan,out);self.assertEqual([],calls);self.assertFalse(runner.requests)
    def test_no_model_decision_no_automatic_split(self):
        runner=Runner(None)
        out,segments,_,_=review(self.doc,self.plan,self.segments,runner)
        self.assertEqual(1,len(out['units']));self.assertEqual(self.segments,segments)

    def test_children_of_model_split_are_reviewed_once_without_rule_boundaries(self):
        text='管道缺失。墙面空鼓。电梯更换。消防缺失。'
        class ChildRunner:
            def __init__(self):self.requests=[]
            def call(self,system,payload,doc,phase):
                self.requests.append(payload);target=payload['target_text']
                starts=['墙面空鼓。'] if target==text else ['电梯更换。','消防缺失。'] if target=='墙面空鼓。电梯更换。消防缺失。' else []
                parts=[{'from_target_start':True,'scope_reason':'首对象','relevant':True,'boundary_confidence':.95}]
                parts += [{'start_quote':q,'scope_reason':'独立对象','relevant':True,'boundary_confidence':.95} for q in starts]
                return {'repairs':[{'unit_index':0,'action':'split' if starts else 'keep',
                    'why':'模型核对实际对象','units':parts if starts else []}]},{'status':'success'}
        runner=ChildRunner();segments=[{'id':1,'start':0,'end':len(text),'text':text}]
        out,new,audit,calls=review(dict(self.doc,text=text),self.plan,segments,runner)
        self.assertEqual(4,len(out['units']));self.assertEqual(text,''.join(s['text'] for s in new))
        self.assertEqual(3,len(calls));self.assertEqual({0,1},{a['review_depth'] for a in audit})
        self.assertTrue(all(p['source_text']==text for p in runner.requests))


if __name__=='__main__':unittest.main()
