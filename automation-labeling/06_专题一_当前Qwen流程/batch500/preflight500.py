"""Read-only input and heat-baseline reconciliation for the authorized 500 sources."""
import csv,hashlib,importlib.util,json,sys
from pathlib import Path
sys.dont_write_bytecode=True;sys.stdout.reconfigure(encoding='utf8')
root=Path(__file__).parent
def read(p):return json.loads(p.read_text(encoding='utf8'))
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
manifest=read(root/'input_manifest.json');heat_manifest=read(root/'heat_baseline_manifest.json')
assert sha(Path(manifest['source_workbook']))==manifest['source_workbook_sha256']
assert sha(root/'documents.json')==manifest['input_sha256']
assert sha(root/'full_two_topic_heat_baseline.csv')==heat_manifest['sha256']
docs=read(root/'documents.json')
assert len(docs)==500 and len({d['source_id'] for d in docs})==500
spec=importlib.util.spec_from_file_location('heat','C:/Users/YS-Insight/Desktop/陈晓锋/自动化打标/04_专题二_观点信息单元/topic2_heat_v110.py')
heat=importlib.util.module_from_spec(spec);spec.loader.exec_module(heat)
with (root/'full_two_topic_heat_baseline.csv').open(encoding='utf-8-sig',newline='') as f:rows={str(r['id']):r for r in csv.DictReader(f)}
checks=0
for d in docs:
    assert d['source_id'] in rows,d['source_id']
    r=rows[d['source_id']]
    for field in ('平台','内容类型','项目',*heat.FIELDS):
        if field not in d['row']:continue
        value=d['row'][field];baseline=r.get(field)
        equal=(heat.count_value(value)==heat.count_value(baseline)) if field in heat.FIELDS else (('' if value is None else str(value))==('' if baseline is None else str(baseline)))
        assert equal,(d['source_id'],field,value,baseline)
        checks+=1
report={'input_articles':500,'unique_source_ids':500,'heat_baseline_articles':len(rows),'matched_heat_sources':500,'interaction_field_checks':checks,'original_workbook_unchanged':True,'first_ten_result_sha256':sha(root/'results_10.json')}
(root/'preflight500.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
print(json.dumps(report,ensure_ascii=False))
