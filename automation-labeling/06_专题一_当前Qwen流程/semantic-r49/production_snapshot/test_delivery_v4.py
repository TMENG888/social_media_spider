"""Offline contract regression, never a fabricated model quality evaluation."""
import copy
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch
import delivery_v4 as v


TAG={'tag_id':'VOC-0234','source_number':'233','l1':'产品','l2':'精装','l3':'通用设备','l4':'中央空调','l5':'','emphasis':'中央空调','instruction':'空调设备','topics':[v.T1,v.T2]}
BUS={'projects':[{'id':'P01','name':'北京臻澐','role':'本品','aliases':['北京臻澐','臻澐'],'confirmation':'本品已指定'}],
     'entities':[{'brand':'中海','entity':'中海地产'}]}


def parent():
    return {'id':'8000912876517502636','文章id':'platform-1','文章链接':'url-1','平台':'小红书','项目':v.T2,'文章内容':'北京臻澐精装配置中央空调。','文章标题':'北京臻澐介绍','热度指数':'0','互动深度指数':'12.3456'}


def fixture(kind='文章',topic=v.T2):
    p=parent();p['项目']=topic
    row=p if kind=='文章' else {'id':'90001','评论id':'c-1','评论内容':'臻澐有中央空调吗？','平台':'小红书','评论时间':'2026-10-01'}
    text=p['文章内容'] if kind=='文章' else row['评论内容']
    d=v.make_document(row,kind,p,'文章内容' if kind=='文章' else '评论内容',text)
    unit={'start':0,'end':len(text),'excerpt':text,'summary':'北京臻澐精装配置中央空调。' if kind=='文章' else '询问臻澐是否配置中央空调。',
          'practice':'住宅精装配置中央空调设备。','brand':'中海','entity':'中海地产','project_name':'北京臻澐','city':None,
          'project_ids':['P01'],'project_evidence':[{'id':'P01','evidence':'北京臻澐','why':'父文标题与当前评价对象一致'}],
          'publisher_role':'普通账号','expression_types':['事实介绍'] if kind=='文章' else ['需求提问'],'emotions':['无态度'],
          'innovation_type':'无明确创新类型','innovation_level':'I0 无创新判断','innovation_evidence':'无升级基线',
          'labels':[{'tag_id':TAG['tag_id'],'evidence':text,'why':'原文明确空调对象和配置','project_ids':['P01'],'confidence':0.95}],
          'confidence':dict.fromkeys(['boundary','summary','project','metadata'],0.95),'uncertainties':[]}
    review={'pass':True,'confidence':0.95,'issues':[],'label_checks':[{'tag_id':TAG['tag_id'],'supported':True,'confidence':0.95,'reason':'证据对应设备'}]}
    return d,unit,review


class Contracts(unittest.TestCase):
    def test_source_priority(self):
        self.assertEqual(v.choose_source({'文章内容':'正文','文章视频内容':'视频','文章图片信息':'OCR'}),('文章内容','正文'))
        self.assertEqual(v.choose_source({'文章内容':' NULL ','文章视频内容':'视频','文章图片信息':'OCR'}),('文章视频内容','视频'))
        self.assertEqual(v.choose_source({'文章内容':'\n','文章视频内容':'','文章图片信息':'OCR'}),('文章图片信息','OCR'))

    def test_eight_keys_and_null_level(self):
        t=v.label_json(TAG);self.assertEqual(list(t),v.TAG_KEYS);self.assertIsNone(t['五级标签']);self.assertEqual(t['标签编号'],233)

    def test_zero_label_number(self):
        self.assertEqual(v.label_json(dict(TAG,source_number='0'))['标签编号'],0)

    def test_schema_order(self):
        for fields in [v.PRODUCT_FIELDS,v.VIEW_FIELDS]:
            self.assertEqual(fields[fields.index('标签明细')-1],'打标说明');self.assertEqual(fields[fields.index('备注')+1],'验收状态')
        self.assertEqual(v.VIEW_FIELDS[2],'映射文章id');self.assertNotIn('产品体系',v.PRODUCT_FIELDS)

    def test_comment_parent_and_full_text(self):
        d,u,r=fixture('评论');result,issues=v.validated_unit(d,u,0,d['text'],[TAG],BUS,r)
        row,trace=result;self.assertFalse(issues);self.assertEqual(row['映射文章id'],parent()['id']);self.assertEqual(row['原始摘录'],d['text'])
        self.assertEqual(row['project_id'],['P01']);self.assertEqual(row['热度指数'],0);self.assertEqual(row['验收状态'],'自动通过')
        self.assertEqual(set(row),set(v.VIEW_FIELDS));self.assertEqual(trace['所属文章ODS主键'],parent()['id'])

    def test_article_parent_column_blank(self):
        d,u,r=fixture();result,_=v.validated_unit(d,u,0,d['text'],[TAG],BUS,r);self.assertIsNone(result[0]['映射文章id'])

    def test_multiplatform_real_sampling_and_complete_comments(self):
        business=v.load_business()
        docs,manifest=v.sample_documents(v.read_csv(Path('C:/Users/YS-Insight/Desktop/ods_social_media_post.csv')),
                                        v.read_csv(Path('C:/Users/YS-Insight/Desktop/ods_social_media_comment.csv')),business)
        from collections import Counter
        posts=[d for d in docs if d['kind']=='文章'];comments=[d for d in docs if d['kind']=='评论']
        self.assertEqual(Counter(d['row']['平台'] for d in posts if d['topic']==v.T1),
                         {'微信公众号':8,'小红书':8,'微信视频号':7,'网页':7})
        self.assertEqual(Counter(d['row']['平台'] for d in posts if d['topic']==v.T2),
                         {'微信公众号':10,'小红书':30,'网页':10})
        self.assertEqual(len(comments),sum(r['关联评论数'] for r in manifest['samples'] if r['专题']==v.T2))
        self.assertEqual(len(set(d['parent']['id'] for d in comments)),30)
        self.assertTrue(all(d['text']==d['row']['评论内容'] for d in comments))
        again,_=v.sample_documents(v.read_csv(Path('C:/Users/YS-Insight/Desktop/ods_social_media_post.csv')),
                                  v.read_csv(Path('C:/Users/YS-Insight/Desktop/ods_social_media_comment.csv')),business)
        self.assertEqual([d['record_id'] for d in docs],[d['record_id'] for d in again])

    def test_multi_project_comment_aligned_arrays(self):
        d,u,r=fixture('评论');d['text']=d['row']['评论内容']='臻澐的空调不错，海晏的空调不好。'
        u.update(excerpt=d['text'],start=0,end=len(d['text']),summary='评价臻澐空调较好，对海晏空调不满意。',project_ids=['P01','C01'],
                 project_evidence=[{'id':'P01','evidence':'臻澐','why':'直接提及对象'}, {'id':'C01','evidence':'海晏','why':'直接提及对象'}],
                 expression_types=['正向评价','负向评价'],emotions=['正向','负向'])
        u['labels'][0].update(evidence=d['text'],project_ids=['P01','C01'],why='臻澐空调正向、海晏空调负向，分别有证据')
        bus=copy.deepcopy(BUS);bus['projects'].append({'id':'C01','name':'建发海晏','role':'核心竞品','aliases':['海晏'],'confirmation':'候选待确认'})
        result,_=v.validated_unit(d,u,0,d['text'],[TAG],bus,r)
        self.assertEqual(result[0]['project_id'],['P01','C01'])
        self.assertEqual(result[0]['项目名称'],['北京臻澐','建发海晏'])
        self.assertEqual(result[0]['项目角色'],['本品','核心竞品'])
        self.assertEqual(result[0]['情绪态度'],'正向;负向')

    def test_partial_comment_rejected(self):
        d,u,r=fixture('评论');u['excerpt']='中央空调';u['start']=4;u['end']=8
        result,issues=v.validated_unit(d,u,0,d['text'],[TAG],BUS,r);self.assertIsNone(result);self.assertIn('评论被切分',issues[0])

    def test_confidence_boundary(self):
        self.assertEqual(v.auto_status([.9,.95],[],True),'自动通过');self.assertEqual(v.auto_status([.89999],[],True),'需人工审核')
        for values in [[None],[float('nan')],[True],[1.1]]:self.assertEqual(v.auto_status(values,[],True),'需人工审核')

    def test_low_reviewer_has_reason(self):
        d,u,r=fixture();r['confidence']=.8;result,_=v.validated_unit(d,u,0,d['text'],[TAG],BUS,r)
        self.assertEqual(result[0]['验收状态'],'需人工审核');self.assertIn('语义验收置信度',result[0]['备注'])

    def test_low_tag_reviewer_has_reason(self):
        d,u,r=fixture();r['label_checks'][0]['confidence']=.89
        result,_=v.validated_unit(d,u,0,d['text'],[TAG],BUS,r)
        self.assertEqual(result[0]['验收状态'],'需人工审核');self.assertIn('标签语义验收置信度',result[0]['备注'])

    def test_unsupported_removed(self):
        d,u,r=fixture();r['label_checks'][0]['supported']=False;result,_=v.validated_unit(d,u,0,d['text'],[TAG],BUS,r)
        self.assertEqual(result[0]['标签明细'],[]);self.assertEqual(result[0]['验收状态'],'需人工审核')

    def test_invalid_evidence_removed(self):
        d,u,r=fixture();u['labels'][0]['evidence']='并未出现的新风';result,_=v.validated_unit(d,u,0,d['text'],[TAG],BUS,r)
        self.assertEqual(result[0]['标签明细'],[])

    def test_product_copy_cannot_pass(self):
        d,u,r=fixture(topic=v.T1);u['practice']=d['text'];result,_=v.validated_unit(d,u,0,d['text'],[TAG],BUS,r)
        self.assertEqual(result[0]['具体产品做法'],'');self.assertIn('直接复制',result[0]['备注']);self.assertEqual(set(result[0]),set(v.PRODUCT_FIELDS))

    def test_unknown_numbers_blocked(self):
        d,u,r=fixture();u['summary']='北京臻澐配置5台中央空调';result,_=v.validated_unit(d,u,0,d['text'],[TAG],BUS,r)
        self.assertEqual(result[0]['观点摘要'],'')

    def test_rule_candidates_not_cut_to_top_n(self):
        tags=[dict(TAG,tag_id='VOC-'+str(i)) for i in range(80)]
        self.assertEqual(len(v.candidates('中央空调',v.T1,tags)),80)

    def test_comment_single_window(self):
        d,_,_=fixture('评论');d['text']='文'*10000;self.assertEqual(v.windows(d),[(0,10000)])

    def test_windows_reconstruct_exact_source(self):
        d,_,_=fixture();d['text']='测试内容。'*2000;self.assertEqual(''.join(d['text'][a:b] for a,b in v.windows(d)),d['text'])

    def test_long_article_single_full_input_even_with_legacy_size(self):
        d,_,_=fixture();d['text']='南向户型介绍。'*300+'北向户型延续介绍。'+'全文末尾。'
        self.assertGreater(len(d['text']),1800)
        self.assertEqual(v.windows(d),[(0,len(d['text']))])
        self.assertEqual(v.windows(d,size=100),[(0,len(d['text']))])

    def test_full_article_generation_and_review_no_rule_preslices(self):
        d,u,r=fixture()
        d['text']='北京臻澐住宅配置说明。'+'南向空间介绍。'*300+'北向中央空调配置。全文末尾。'
        segments=v.evidence_segments(d['text'],'文章')
        u.pop('start');u.pop('end');u.pop('excerpt')
        u.update(source_start_id=1,source_end_id=len(segments))
        u['labels'][0].pop('evidence')
        evidence_id=next(s['id'] for s in segments if '中央空调' in s['text'])
        u['labels'][0].update(evidence_start_id=evidence_id,evidence_end_id=evidence_id)
        class Runner:
            def __init__(self):self.inputs=[]
            def call(self,system,payload,doc,phase):
                self.inputs.append((phase,copy.deepcopy(payload)))
                answer={'units':[copy.deepcopy(u)]} if phase=='生成' else {'checks':[dict(copy.deepcopy(r),index=0)]}
                return answer,{'status':'success'}
        runner=Runner();result=v.process_document(d,[TAG],BUS,runner)
        self.assertEqual([p for p,_ in runner.inputs],['生成','语义校验'])
        self.assertEqual(len(result['rows']),1)
        self.assertEqual(result['rows'][0]['原始摘录'],d['text'])
        self.assertEqual(result['rows'][0]['验收状态'],'自动通过')
        for _,payload in runner.inputs:
            self.assertEqual(payload['window_text'],d['text'])
            self.assertEqual(payload['input_scope'],'full_document')
            self.assertEqual(''.join(s['text'] for s in payload['source_segments']),d['text'])
            self.assertNotIn('rule_preslices',payload)
            self.assertNotIn('max_article_excerpt_chars',payload['delivery_contract'])
        self.assertNotIn('语义切片超过600字',result['rows'][0]['备注'])

    def test_comment_full_parent_context_and_single_unit(self):
        d,u,r=fixture('评论');d['parent']['文章内容']='背景介绍。'*400+'北京臻澐精装配置中央空调。'
        class Runner:
            def __init__(self):self.inputs=[]
            def call(self,system,payload,doc,phase):
                self.inputs.append(copy.deepcopy(payload))
                answer={'units':[copy.deepcopy(u)]} if phase=='生成' else {'checks':[dict(copy.deepcopy(r),index=0)]}
                return answer,{'status':'success'}
        runner=Runner();result=v.process_document(d,[TAG],BUS,runner)
        self.assertEqual(len(result['rows']),1)
        self.assertEqual(result['rows'][0]['原始摘录'],d['text'])
        for payload in runner.inputs:
            self.assertEqual(payload['parent_article_context'],d['parent']['文章内容'])
            self.assertEqual(payload['window_text'],d['text'])

    def test_fulltext_prompt_uses_object_not_length(self):
        self.assertIn('完整全文',v.SYSTEM)
        self.assertIn('同一项目、同一户型的连续配置介绍',v.SYSTEM)
        self.assertIn('切片长度由语义完整性决定',v.SYSTEM)
        self.assertNotIn('一片最好1~3句',v.SYSTEM)

    def test_sentence_id_evidence_lossless(self):
        text=' 设备A。\n设备B； 尾句'
        segments=v.evidence_segments(text,'文章')
        self.assertEqual(''.join(s['text'] for s in segments),text)
        raw={'units':[{'source_ids':[1,2,3],'excerpt':'模型改写无效','labels':[{'evidence_ids':[3],'evidence':'伪造'}]}]}
        result=v.materialize_evidence(raw,segments,text)['units'][0]
        self.assertEqual(result['excerpt'],''.join(s['text'] for s in segments[:3]))
        self.assertEqual(result['labels'][0]['evidence'],segments[2]['text'])

    def test_noncontinuous_sentence_ids_refused(self):
        text='甲。乙。丙。';segments=v.evidence_segments(text,'文章')
        result=v.materialize_evidence({'units':[{'source_ids':[1,3],'labels':[]}]},segments,text)
        self.assertEqual(result['units'][0]['excerpt'],'')

    def test_scalar_evidence_interval(self):
        text='甲。乙。丙。';segments=v.evidence_segments(text,'文章')
        raw={'units':[{'source_start_id':2,'source_end_id':3,'labels':[{'evidence_start_id':3,'evidence_end_id':3}]}]}
        u=v.materialize_evidence(raw,segments,text)['units'][0]
        self.assertEqual(u['excerpt'],'乙。丙。');self.assertEqual(u['labels'][0]['evidence'],'丙。')

    def test_coverage_repair_requires_real_evidence_legal_id(self):
        review={'missing_labels':[{'evidence':'中央空调','tag_id':TAG['tag_id']},
                                  {'evidence':'中央空调','tag_id':'VOC-FAKE'},
                                  {'evidence':'新风','tag_id':TAG['tag_id']}],
                'missing_facts':[{'evidence':'无原文信息'}]}
        result=v.coverage_feedback(review,'中央空调',[TAG],v.T2)
        self.assertEqual(len(result),1)

    def test_offline_never_auto(self):
        d,u,r=fixture();result,_=v.validated_unit(d,u,0,d['text'],[TAG],BUS,r,'offline');self.assertEqual(result[0]['验收状态'],'需人工审核')

    def test_ambiguous_comment_mapping(self):
        p=parent();other=dict(p,id='2',文章链接='url-2');index=v.PostIndex([p,other]);c={'平台':'小红书','文章id':p['文章id']}
        self.assertIsNone(index.map_comment(c)[0])

    def test_auth_stops_and_does_not_retry(self):
        class Response:status_code=401
        with tempfile.TemporaryDirectory() as out,patch.object(v,'post_json',return_value=Response()) as post:
            runner=v.ApiRunner(out,key='test-not-a-real-key');d,_,_=fixture()
            runner.call('test',{},d,'生成');self.assertTrue(runner.fatal.is_set());self.assertEqual(post.call_count,1)

    def test_success_cache_prevents_rebill(self):
        class Response:
            status_code=200
            def json(self):return {'choices':[{'message':{'content':'{"units":[]}'}}],'usage':{'prompt_tokens':100,'completion_tokens':20,'total_tokens':120}}
        with tempfile.TemporaryDirectory() as out,patch.object(v,'post_json',return_value=Response()) as post:
            runner=v.ApiRunner(out,key='test-not-a-real-key');d,_,_=fixture()
            runner.call('test',{},d,'生成');_,metrics=runner.call('test',{},d,'生成')
            self.assertEqual(post.call_count,1);self.assertTrue(metrics['cache_hit'])

    def test_truncated_output_not_accepted_even_if_valid_json(self):
        class Response:
            status_code=200
            def json(self):return {'choices':[{'finish_reason':'length','message':{'content':'{"units":[]}'}}],
                                   'usage':{'prompt_tokens':100,'completion_tokens':20,'total_tokens':120}}
        with tempfile.TemporaryDirectory() as out,patch.object(v,'post_json',return_value=Response()) as post:
            runner=v.ApiRunner(out,key='test-not-a-real-key');d,_,_=fixture()
            response,metrics=runner.call('test',{},d,'生成')
            self.assertIsNone(response);self.assertEqual(metrics['status'],'failed_json')
            self.assertEqual(metrics['total_tokens'],120)
            self.assertEqual(post.call_args.args[1]['max_tokens'],v.MAX_OUTPUT_TOKENS)

    def test_global_request_concurrency(self):
        current=0;peak=0;lock=threading.Lock()
        class Response:
            status_code=200
            def json(self):return {'choices':[{'message':{'content':'{"units":[]}'}}],'usage':{}}
        def post(*args,**kwargs):
            nonlocal current,peak
            with lock:current+=1;peak=max(peak,current)
            time.sleep(.01)
            with lock:current-=1
            return Response()
        with tempfile.TemporaryDirectory() as out,patch.object(v,'post_json',side_effect=post):
            runner=v.ApiRunner(out,concurrency=2,key='test-not-a-real-key');d,_,_=fixture()
            with ThreadPoolExecutor(max_workers=10) as pool:list(pool.map(lambda i:runner.call('test',{'i':i},d,'校验'),range(10)))
        self.assertLessEqual(peak,2)

    def test_concurrency_above_ten_is_rejected(self):
        with tempfile.TemporaryDirectory() as out:
            with self.assertRaises(ValueError):v.ApiRunner(out,concurrency=11,key='test-not-a-real-key')


if __name__=='__main__':unittest.main(verbosity=2)
