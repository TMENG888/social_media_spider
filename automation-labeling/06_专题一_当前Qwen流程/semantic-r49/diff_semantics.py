"""Read-only Qwen version diff; gold references are not needed or imported."""
import json,sys
from pathlib import Path
sys.stdout.reconfigure(encoding='utf8');R=Path(__file__).parent

def read(p):return json.loads(p.read_text(encoding='utf8'))

def main():
 before,after,*batches=sys.argv[1:];out=[]
 for batch in batches:
  old={x['document']['source_id']:x for x in read(R/f'run_{before}'/f'{batch}_results.json')}
  current=R/f'run_{after}'/f'{batch}_results.json'
  news=read(current) if current.exists() else [read(f)['result'] for f in (R/f'run_{after}/sources').glob('*.json') if read(f)['result']['document']['source_id'] in old]
  for x in news:
   sid=x['document']['source_id'];previous={(u['start'],u['end']):u for u in old[sid]['semantic_partition']}
   for u in x['semantic_partition']:
    v=previous.get((u['start'],u['end']))
    if v is None:out.append({'batch':batch,'sid':sid,'boundary_changed':True,'raw':u['text']});continue
    bt={t['tag_id'] for t in v['labels']};at={t['tag_id'] for t in u['labels']}
    if bt!=at or v.get('practice')!=u.get('practice') or v['deliver']!=u['deliver']:
     out.append({'batch':batch,'sid':sid,'index':u['index'],'raw':u['text'],'removed':sorted(bt-at),'added':sorted(at-bt),
                 'new_proofs':[t for t in u['labels'] if t['tag_id'] in at-bt],
                 'old':v.get('practice'),'new':u.get('practice'),'deliver':u['deliver'],'fallback':u.get('summary_fallback')})
 print(json.dumps(out,ensure_ascii=False))

if __name__=='__main__':main()
