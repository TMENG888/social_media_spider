import json,sys
from pathlib import Path
from collections import Counter
sys.stdout.reconfigure(encoding='utf8');R=Path(__file__).parent
import evaluate as ev
def read(p):return json.loads(Path(p).read_text(encoding='utf8'))
tax={t['tag_id']:t for t in read(R/'inputs/taxonomy.json')}
ref=ev.refs('A');gold={sid:set().union(*(ev.tags(u['标签明细']) for u in ref if str(u['源表id'])==sid)) for sid in {str(u['源表id']) for u in ref}}
out=[];counts=Counter()
for result in read(R/'r8_audit/results.json'):
 sid=result['document']['source_id'];before=set().union(*(ev.tags(v) for v in result['labels_before_review'].values()));after=set().union(*(ev.tags(u['标签明细']) for u in result['rows']));gt=gold[sid]
 cases=[]
 for kind,ids in [('初标漏选',gt-before),('复核误删候选',(before-after)&gt),('初标多标候选',before-gt),('复核新增多标候选',(after-before)-gt)]:
  for tid in sorted(ids):
   t=tax[tid];proofs=[{'unit':u['index'],'quote':p['quote'],'reason':p['reason']} for u in result['semantic_partition'] for p in u['labels'] if p['tag_id']==tid]
   beforeproof=[{'unit':i,**p} for i,ps in result['labels_before_review'].items() for p in ps if p['tag_id']==tid]
   rf=[{'quote':u['原文摘录'],'why':u['打标说明'],'practice':u['具体产品做法']} for u in ref if str(u['源表id'])==sid and tid in ev.tags(u['标签明细'])]
   cases.append({'kind':kind,'tag_id':tid,'path':'/'.join(t[k] for k in ['l1','l2','l3','l4','l5'] if t[k]),'definition':t['instruction'],'before_proofs':beforeproof,'final_proofs':proofs,'reference_proofs':rf});counts[kind]+=1
 out.append({'source_id':sid,'title':result['document']['title'],'before':sorted(before),'after':sorted(after),'removed':sorted(before-after),'added':sorted(after-before),'cases':cases})
(R/'r8_audit/diagnosis.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf8')
print(json.dumps({'counts':dict(counts),'sources':[{k:x[k] for k in ['source_id','removed','added']} for x in out]},ensure_ascii=False))
