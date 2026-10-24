import argparse,importlib.util,json,sys
from pathlib import Path
sys.dont_write_bytecode=True;sys.stdout.reconfigure(encoding='utf8')
ROOT=Path(__file__).parent
PROJECT=Path(__file__).resolve().parents[1]/'semantic-r49'
p=argparse.ArgumentParser();p.add_argument('--count',type=int,choices=[10,500],default=10);args=p.parse_args();count=args.count
docs=json.loads((ROOT/'documents.json').read_text(encoding='utf8'))[:count]
results=json.loads((ROOT/f'results_{count}.json').read_text(encoding='utf8'))
assert len(results)==count and [r['document']['record_id'] for r in results]==[d['record_id'] for d in docs]
input_path=ROOT/'documents.json' if count==500 else ROOT/'documents_10.json'
if count==10:input_path.write_text(json.dumps(docs,ensure_ascii=False,indent=2),encoding='utf8')
if count==500:
    previous=json.loads((ROOT/'results_10.json').read_text(encoding='utf8'))
    assert results[:10]==previous,'Confirmed first ten results must remain unchanged'
spec=importlib.util.spec_from_file_location('delivery',PROJECT/'prepare_regression_delivery.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
module.prepare(str(count),'r49',source_path=ROOT/f'results_{count}.json',input_path=input_path,dest_dir=ROOT/f'delivery{count}',heat_baseline_files=[ROOT/'full_two_topic_heat_baseline.csv'])
plan_path=ROOT/f'delivery{count}/{count}_delivery_plan.json'
plan=json.loads(plan_path.read_text(encoding='utf8'))
plan['delivery_kind']='10篇试标' if count==10 else '批量'
for sheet in plan['sheets']:
    if sheet['name']=='产品信息单元':
        label_index=sheet['headers'].index('标签明细')
        assert all(json.loads(r[label_index]) for r in sheet['rows'])
    for row in sheet['rows']:
        assert all(not isinstance(v,str) or len(v.encode('utf-16-le'))//2<=32767 for v in row)
plan_path.write_text(json.dumps(plan,ensure_ascii=False,indent=2),encoding='utf8')
print(json.dumps({'sources':plan['source_count'],'units':plan['unit_count'],'partition_count':plan['partition_count'],'empty_delivery_rows':0,'remaining_490_started':count==500},ensure_ascii=False))
