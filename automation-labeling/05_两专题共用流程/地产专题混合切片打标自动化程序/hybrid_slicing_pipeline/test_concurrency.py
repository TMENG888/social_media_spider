"""Offline concurrency regression test; makes no network calls."""
import contextlib,csv,io,json,sys,tempfile,threading,time
from pathlib import Path
from unittest.mock import patch
import run_api_50_test as runner

lock=threading.Lock();active=0;peak=0
class Session:
    def close(self): pass
class FakeClient:
    def __init__(self,*args,**kwargs): self.session=Session()
    def chat_json(self,system,prompt):
        global active,peak
        request=json.loads(prompt)
        with lock:active+=1;peak=max(peak,active)
        time.sleep(.025)
        with lock:active-=1
        units=[{'source_unit_ids':[u['unit_id']],'project':u['project'],'tag_id':u['tag_id'],'confidence':.95,'practice_or_summary':'证据中的产品做法'} for u in request['candidate_units']]
        return {'units':units},{'status':'success','http_status':200,'prompt_tokens':8,'cached_input_tokens':0,'completion_tokens':2,'total_tokens':10,'latency_seconds':.025,'retries':0,'api_cost':None,'request_id':'mock','error':''}

with tempfile.TemporaryDirectory(prefix='voc_concurrency_test_') as directory:
    root=Path(directory);ids=[str(9000000000000000000+i) for i in range(12)]
    with (root/'input.csv').open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=['id','项目','文章内容','文章标题','平台']);writer.writeheader()
        writer.writerows({'id':i,'项目':runner.TOPIC1,'文章内容':'项目采用架空层。','文章标题':'标题','平台':'小红书'} for i in ids)
    (root/'config.json').write_text(json.dumps({'sample_ids':ids}),encoding='utf-8')
    units=[{'content_id':'P-'+i,'unit_id':f'T1-{i}-{j}','标签路径ID':f'VOC-{j:04d}','项目':'项目A','原文摘录':'项目采用架空层。'} for i in ids for j in range(8)]
    (root/'rule.json').write_text(json.dumps({'product_units':units,'viewpoint_units':[]}),encoding='utf-8')
    argv=['test','--input',str(root/'input.csv'),'--config',str(root/'config.json'),'--rule-json',str(root/'rule.json'),'--output-dir',str(root/'out'),'--concurrency','4','--candidate-batch-size','6']
    with patch.object(sys,'argv',argv),patch.object(runner,'LlmApiClient',FakeClient),contextlib.redirect_stdout(io.StringIO()):runner.main()
    summary=json.loads((root/'out/api_test_summary.json').read_text(encoding='utf-8'))
    with (root/'out/文章Token成本.csv').open(encoding='utf-8-sig',newline='') as f: articles=list(csv.DictReader(f))
    assert peak==4 and active==0,peak
    assert summary['api_calls']==24 and summary['successful_articles']==12,summary
    assert summary['all_calls_total_tokens']==240
    assert [r['源表id'] for r in articles]==ids
print('PASS: max HTTP concurrency=4; 2 sequential batches/article; deterministic article order; exact usage accounting; no API calls.')
