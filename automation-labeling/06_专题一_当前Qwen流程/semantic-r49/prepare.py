import json,hashlib,sys
from pathlib import Path
sys.stdout.reconfigure(encoding='utf8');R=Path(__file__).parent
def read(p):return json.loads(Path(p).read_text(encoding='utf8'))
def save(p,x):Path(p).write_text(json.dumps(x,ensure_ascii=False,indent=2),encoding='utf8')
inputs=R/'inputs';inputs.mkdir(exist_ok=True)
files={'A_documents.json':'E:/Codex/work/20261021_专题一参考集A_双模型隔离/documents.json','B_documents.json':'E:/Codex/work/20261021_专题一参考集BC/B_documents.json','C_documents.json':'E:/Codex/work/20261021_专题一参考集BC/C_documents.json','taxonomy.json':'E:/Codex/work/20261021_专题一参考集A_双模型隔离/taxonomy_runtime.json','brand_dictionary.json':'E:/Codex/work/20261021_专题一经营主体完善/brand_dictionary_full.json'}
for name,p in files.items():
 x=read(p)
 if name=='taxonomy.json':x=[t for t in x if '全国地产设计产品力监测' in t['topics']]
 save(inputs/name,x)
manifest={'inputs':{},'references':{},'implementation_snapshot':{},'batch_scope':300,'batch_started':False,'gates':{'structure_errors':0,'duplicate_slices':0,'empty_practice':0,'critical_object_or_negation_errors':0,'source_tag_precision_min':.95,'source_tag_recall_min':.95,'span_tag_precision_min':.90,'span_tag_recall_min':.90,'semantic_review_required':True},'workflow':'A调试→B验证→修改重测A/B→冻结→C验收；C在冻结前只做文件哈希封存，不做标签或效果评测。'}
for p in inputs.glob('*.json'):manifest['inputs'][p.name]=hashlib.sha256(p.read_bytes()).hexdigest()
for p in Path('E:/Codex/outputs/20261021_专题一参考集ABC').glob('*.xlsx'):
 if not p.name.startswith('~$'):manifest['references'][p.name]=hashlib.sha256(p.read_bytes()).hexdigest()
for p in (R/'production_snapshot').glob('*.py'):manifest['implementation_snapshot'][p.name]=hashlib.sha256(p.read_bytes()).hexdigest()
save(R/'manifest.json',manifest)
print(json.dumps({'snapshot_files':len(manifest['implementation_snapshot']),'topic1_taxonomy':len(read(inputs/'taxonomy.json')),'batches':[len(read(inputs/f'{b}_documents.json')) for b in 'ABC'],'gates':manifest['gates']},ensure_ascii=False))
