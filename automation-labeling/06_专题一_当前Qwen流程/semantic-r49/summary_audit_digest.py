"""Offline quality digest; outputs are never imported by model runners."""
import sys,json
from pathlib import Path
sys.stdout.reconfigure(encoding='utf8');R=Path(__file__).parent
version,batch=sys.argv[1:3]
raw=json.loads((R/f'run_{version}'/f'{batch}_results.json').read_text(encoding='utf8'))
old=json.loads((R/'run_r24'/f'{batch}_results.json').read_text(encoding='utf8'))
old_by={r['document']['source_id']:r for r in old}
changes=[];fallbacks=[];rows=[]
for r in raw:
    sid=r['document']['source_id'];previous=old_by[sid]
    for u in r['semantic_partition']:
        p=next(p for p in previous['semantic_partition'] if p['start']==u['start'] and p['end']==u['end'])
        if {t['tag_id'] for t in u['labels']}!={t['tag_id'] for t in p['labels']}:
            changes.append({'source_id':sid,'index':u['index'],'before':p['labels'],'after':u['labels'],'text':u['text']})
        if u.get('summary_fallback'):fallbacks.append({'source_id':sid,'index':u['index'],'fallback':u['summary_fallback']})
        if u['deliver']:rows.append({'source_id':sid,'index':u['index'],'raw':u['text'],'summary':u['practice'],
          'repaired':u.get('summary_fidelity_audit',{}).get('repaired',False),'fallback':bool(u.get('summary_fallback'))})
digest={'version':version,'batch':batch,'sources':len(raw),'delivery_units':len(rows),'fallbacks':fallbacks,'label_changes':changes,'rows':rows}
(R/f'run_{version}'/f'{batch}_summary_audit.json').write_text(json.dumps(digest,ensure_ascii=False,indent=2),encoding='utf8')
print(json.dumps({k:v for k,v in digest.items() if k!='rows'},ensure_ascii=False))
if len(sys.argv)>3:
    for row in rows:
        if row['source_id'] in sys.argv[3:]:print(json.dumps(row,ensure_ascii=False))
