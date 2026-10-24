"""Freeze successful source caches and prepare an offline interim delivery."""
import importlib.util,json,sys,hashlib
from pathlib import Path
from datetime import datetime,timezone
sys.dont_write_bytecode=True
sys.stdout.reconfigure(encoding='utf8')
ROOT=Path(__file__).parent
PROJECT=Path(__file__).resolve().parents[1]/'semantic-r49'
stamp=datetime.now().strftime('%Y%m%d_%H%M%S')
folder=ROOT/f'interim_{stamp}'
folder.mkdir()
docs=json.loads((ROOT/'documents.json').read_text(encoding='utf8'))
paths={d['record_id']:ROOT/'sources'/f"{d['record_id']}.json" for d in docs}
available={rid:p for rid,p in paths.items() if p.exists()}
selected=[];results=[]
for d in docs:
    if d['record_id'] not in available:continue
    cached=json.loads(available[d['record_id']].read_text(encoding='utf8'))
    result=cached['result']
    assert result['complete'] and result['document']==d
    selected.append(d);results.append(result)
assert results
confirmed=json.loads((ROOT/'results_10.json').read_text(encoding='utf8'))
assert results[:10]==confirmed
for name,value in [('documents',selected),('results',results)]:
    (folder/f'{name}.json').write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf8')
batch=f'interim_{len(results)}'
spec=importlib.util.spec_from_file_location('offline_delivery',PROJECT/'prepare_regression_delivery.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
module.prepare(batch,'r49',source_path=folder/'results.json',input_path=folder/'documents.json',dest_dir=folder,heat_baseline_files=[ROOT/'full_two_topic_heat_baseline.csv'])
plan_path=folder/f'{batch}_delivery_plan.json'
plan=json.loads(plan_path.read_text(encoding='utf8'))
note=f'中间快照：已完成{len(results)}篇／计划500篇；其余处理中。指标仅基于本快照，非原顺序前{len(results)}篇。'
plan.update(delivery_kind='中间稿',snapshot_note=note)
for sheet in plan['sheets']:
    if sheet['name'].endswith('议题指标'):
        sheet['notes'].append(['快照范围',note])
    for row in sheet['rows']:
        assert all(not isinstance(v,str) or len(v.encode('utf-16-le'))//2<=32767 for v in row)
plan_path.write_text(json.dumps(plan,ensure_ascii=False,indent=2),encoding='utf8')
output=Path('E:/Codex/outputs')/f'{stamp}_专题一Qwen中间交付'/f'专题一_Qwen中间数据集_{len(results)}篇_标准10工作表.xlsx'
manifest={'batch':batch,'folder':str(folder),'plan':str(plan_path),'output':str(output),'preview':str(folder/'preview'),'source_count':len(results),'unit_count':plan['unit_count'],'partition_count':plan['partition_count'],'snapshot_utc':datetime.now(timezone.utc).isoformat(),'source_ids':[d['record_id'] for d in selected],'annotation_sha256':hashlib.sha256((folder/'results.json').read_bytes()).hexdigest()}
(folder/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf8')
(ROOT/'latest_interim.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf8')
print(json.dumps({k:v for k,v in manifest.items() if k!='source_ids'},ensure_ascii=False))
