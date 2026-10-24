"""Original local FP32 RoBERTa formula, applied to completed slices only.

No Qwen numeric scoring, source-score fallback, database access or downloads.
"""
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import re
import statistics
import subprocess
import sys
import threading

VERSION = 'topic2-local-roberta-slices-20261021-v107'
MODEL = 'uer/roberta-base-finetuned-jd-binary-chinese'
REVISION = '133367c1beb2d5b04e6df3e7ec218a49575bc437'
ORIGINAL = Path('C:/Users/YS-Insight/Documents/Codex/2026-10-14/new-chat')
DEFAULT_MODEL = Path(os.environ.get('LABEL_SENTIMENT_MODEL','E:/Codex/work/models/roberta_sentiment'))
DEFAULT_PYTHON = Path(os.environ.get('LABEL_SENTIMENT_PYTHON',sys.executable))
MARKER = re.compile(r'【(父评论|子评论\d*)[^】]*】')
_guard = threading.RLock()
_identities = {}

def digest(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()

def sha(file):
    h=hashlib.sha256()
    with Path(file).open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()

def save(file,value):
    file=Path(file);file.parent.mkdir(parents=True,exist_ok=True)
    temporary=file.with_name(file.name+'.'+str(threading.get_ident())+'.tmp')
    temporary.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
    temporary.replace(file)

def parsed_messages(text):
    """Copied from original comment scorer; nicknames are not model input."""
    if not isinstance(text,str) or not text.strip():return []
    matches=list(MARKER.finditer(text))
    if not matches:return [('parent',text.strip())]
    result=[];prefix=text[:matches[0].start()].strip()
    if prefix:result.append(('parent',prefix))
    for j,m in enumerate(matches):
        body=text[m.end():matches[j+1].start() if j+1<len(matches) else len(text)].strip()
        if body:result.append(('reply' if m.group(1).startswith('子') else 'parent',body))
    return result

def spans(n):
    if n<=0:raise ValueError('Empty token sequence')
    if n<=510:return [(0,n)]
    width=min(510,math.ceil(n/3))
    return [(s,s+width) for s in (0,(n-width)//2,n-width)]

def identity(folder=DEFAULT_MODEL):
    folder=Path(folder).resolve()
    names=['provenance.json','config.json','vocab.txt','tokenizer_config.json','special_tokens_map.json','model_fp32_explicit_mask.onnx']
    key=tuple((str(folder/n),(folder/n).stat().st_size,(folder/n).stat().st_mtime_ns) for n in names)
    with _guard:
        if key in _identities:return _identities[key]
        provenance=json.loads((folder/'provenance.json').read_text(encoding='utf-8'))
        if provenance!={'model':MODEL,'revision':REVISION}:raise ValueError('Original model revision mismatch')
        cfg=json.loads((folder/'config.json').read_text(encoding='utf-8'))
        if not cfg['id2label']['1'].startswith('positive'):raise ValueError('Positive class mapping mismatch')
        value={'model':MODEL,'revision':REVISION,'precision':'FP32','files':{n:sha(folder/n) for n in names}}
        _identities[key]=value
        return value

def signature(text,model_identity):
    return digest([VERSION,model_identity,parsed_messages(text)])

def _validate(stage,text,model_identity):
    if stage.get('version')!=VERSION or stage.get('model_identity')!=model_identity or stage.get('signature')!=signature(text,model_identity):raise ValueError('Sentiment cache identity mismatch')
    value=stage['response'];groups=stage['messages'];original=parsed_messages(text)
    if len(groups)!=len(original) or not groups:raise ValueError('Sentiment message coverage mismatch')
    for item,(role,body) in zip(groups,original):
        if item['role']!=role or item['text']!=body or body not in text:raise ValueError('Sentiment input mismatch')
        if [(v['start_token'],v['end_token']) for v in item['segments']]!=spans(item['token_count']):raise ValueError('Sentiment span mismatch')
        for v in item['segments']:
            p=v['positive_probability']
            if type(p) not in (float,int) or not math.isfinite(p) or not 0<=p<=1:raise ValueError('Invalid probability')
        if abs(item['positive_probability']-statistics.mean(v['positive_probability'] for v in item['segments']))>1e-12:raise ValueError('Message probability mismatch')
    p=statistics.mean(g['positive_probability'] for g in groups)
    if value['score']!=round(100*p,2) or abs(value['positive_probability']-p)>1e-12:raise ValueError('Score formula mismatch')
    if value['evidence']!=[{'quote':body,'role':role} for role,body in original]:raise ValueError('Input provenance mismatch')
    return value

def infer_batch(texts,folder=DEFAULT_MODEL):
    """Exact latest original formula. Whole thread remains ONE output record."""
    import numpy as np
    from transformers import BertTokenizer
    import onnxruntime as ort
    tokenizer=BertTokenizer.from_pretrained(str(folder),local_files_only=True)
    opts=ort.SessionOptions();opts.intra_op_num_threads=min(20,os.cpu_count() or 4);opts.inter_op_num_threads=1
    opts.graph_optimization_level=ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    session=ort.InferenceSession(str(Path(folder)/'model_fp32_explicit_mask.onnx'),opts,providers=['CPUExecutionProvider'])
    inputs={};records=[]
    for text in texts:
        groups=[]
        for role,body in parsed_messages(text):
            ids=tokenizer.encode(body,add_special_tokens=False,truncation=False)
            if not ids:raise ValueError('Nonempty message has no tokens')
            segments=[]
            for a,b in spans(len(ids)):
                encoded=[tokenizer.cls_token_id]+ids[a:b]+[tokenizer.sep_token_id]
                key=hashlib.sha256(np.asarray(encoded,dtype=np.int32).tobytes()).hexdigest()
                inputs[key]=encoded
                segments.append({'start_token':a,'end_token':b,'token_ids_sha256':key})
            groups.append({'role':role,'text':body,'token_count':len(ids),'segments':segments,
                           'all_tokens_covered':len(set(i for a,b in spans(len(ids)) for i in range(a,b)))==len(ids)})
        if not groups:raise ValueError('Empty slice/comment')
        records.append(groups)
    probabilities={};items=sorted(inputs.items(),key=lambda kv:len(kv[1]))
    for i in range(0,len(items),16):
        batch=items[i:i+16];size=max(len(x) for _,x in batch)
        ids=np.zeros((len(batch),size),np.int64);mask=np.zeros_like(ids)
        for j,(_,x) in enumerate(batch):ids[j,:len(x)]=x;mask[j,:len(x)]=1
        logits=session.run(None,{'input_ids':ids,'attention_mask':mask,'token_type_ids':np.zeros_like(ids)})[0]
        logits-=logits.max(axis=1,keepdims=True);ex=np.exp(logits);p=ex[:,1]/ex.sum(axis=1)
        for (key,_),prob in zip(batch,p):probabilities[key]=float(prob)
    result=[]
    for groups in records:
        for message in groups:
            for segment in message['segments']:segment['positive_probability']=probabilities[segment['token_ids_sha256']]
            message['positive_probability']=statistics.mean(v['positive_probability'] for v in message['segments'])
        prob=statistics.mean(m['positive_probability'] for m in groups)
        result.append({'messages':groups,'response':{'score':round(100*prob,2),'positive_probability':prob,
          'reason':'沿用原FP32情感模型：每段softmax正向概率先在发言内平均，再对本切片全部发言等权平均，乘100并保留两位小数。',
          'evidence':[{'quote':m['text'],'role':m['role']} for m in groups]}})
    return result

class LocalScorer:
    def __init__(self,output_dir,model_dir=DEFAULT_MODEL,python=DEFAULT_PYTHON):
        self.output=Path(output_dir);self.model_dir=Path(model_dir);self.python=Path(python)
        self.identity=identity(self.model_dir)

    def score_many(self,texts):
        texts=list(texts);stages={};missing={}
        with _guard:
            for text in texts:
                if not parsed_messages(text):raise ValueError('Empty slice/comment')
                key=signature(text,self.identity);file=self.output/'sentiment_roberta_stages'/(key+'.json')
                if file.exists():
                    stage=json.loads(file.read_text(encoding='utf-8'));_validate(stage,text,self.identity);stages[key]=stage
                else:missing[key]=text
            if missing:
                batch_id=digest(list(missing));root=self.output/'local_inference'/batch_id
                request=root/'input.json';answer=root/'output.json'
                save(request,{'model_dir':str(self.model_dir),'texts':list(missing.values())})
                env=os.environ.copy();env['PYTHONDONTWRITEBYTECODE']='1';env['HF_HUB_OFFLINE']='1';env['TRANSFORMERS_OFFLINE']='1'
                env['HF_HOME']=str(self.output/'hf_offline');env['TOKENIZERS_PARALLELISM']='false'
                done=subprocess.run([str(self.python),'-B',str(Path(__file__).resolve()),'--infer',str(request),str(answer)],
                                    env=env,capture_output=True,text=True,encoding='utf-8',timeout=900)
                if done.returncode:raise RuntimeError('Local RoBERTa inference failed; labels retained: '+done.stderr[-2000:])
                computed=json.loads(answer.read_text(encoding='utf-8'))
                if len(computed)!=len(missing):raise ValueError('Incomplete local inference')
                for (key,text),result in zip(missing.items(),computed):
                    stage={'version':VERSION,'signature':key,'model':MODEL,'model_identity':self.identity,
                           'source_or_parent_score_used':False,**result}
                    _validate(stage,text,self.identity)
                    save(self.output/'sentiment_roberta_stages'/(key+'.json'),stage);stages[key]=stage
            return [stages[signature(t,self.identity)] for t in texts]

def attach(source,runner,output_dir):
    if source.get('unfinished_units') or set(source['outcomes'])!={u['unit_id'] for u in source['units']} or not source['units']:raise ValueError('Finish all units before sentiment')
    scorer=runner if isinstance(runner,LocalScorer) else LocalScorer(output_dir)
    stages=scorer.score_many(u['text'] for u in source['units'])
    result=copy.deepcopy(source)
    result['slice_sentiment']={'version':VERSION,'units':{u['unit_id']:{'text_sha256':digest(u['text']),'stage':stage} for u,stage in zip(source['units'],stages)},
       'source_mean':statistics.mean(x['response']['score'] for x in stages),'legacy_source_score':source.get('score'),'parent_score_not_used':True}
    return result

def unit_result(record,unit_id):
    unit=next(u for u in record['units'] if u['unit_id']==unit_id)
    report=record['slice_sentiment'];item=report['units'][unit_id]
    if report['version']!=VERSION or item['text_sha256']!=digest(unit['text']):raise ValueError('Sentiment not bound to current slice')
    stage=item['stage']
    return _validate(stage,unit['text'],identity())

def rescore_payload(payload,records):
    result=copy.deepcopy(payload);by={r['record_id']:r for r in records}
    for source in result['sources']:
        r=by[source['record_id']];source['score_legacy']=source['score'];source['score']=statistics.mean(unit_result(r,u['unit_id'])['score'] for u in r['units']);source['score_method']=VERSION
    for u in result['units']:
        value=unit_result(by[u['record_id']],u['原切片ID']);u['情绪评分']=value['score']
        proof=u['项目与标签证据'];proof=json.loads(proof) if isinstance(proof,str) else proof
        u['项目与标签证据']={**proof,'slice_sentiment':value,'sentiment_version':VERSION}
        u['审核口径']+='；当前切片本地RoBERTa评分，不继承来源分'
    for pair in result['pairs']:pair['score']=statistics.mean(unit_result(by[pair['record_id']],uid)['score'] for uid in set(pair['unit_ids']))
    for metric in result['metrics']:
        values=[p['score'] for p in result['pairs'] if p['group']==metric['group'] and p['tag_id']==metric['tag_id']]
        metric['sentiment']=statistics.mean(values) if values else None
    result['sentiment_version']=VERSION
    return result

if __name__=='__main__':
    if len(sys.argv)!=4 or sys.argv[1]!='--infer':raise SystemExit('Internal local inference worker only')
    data=json.loads(Path(sys.argv[2]).read_text(encoding='utf-8'))
    save(sys.argv[3],infer_batch(data['texts'],Path(data['model_dir'])))
