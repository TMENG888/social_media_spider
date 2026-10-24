"""Offline model-to-model-version summary diff, not a gold input."""
import json,sys
from pathlib import Path
sys.stdout.reconfigure(encoding='utf8');R=Path(__file__).parent
version=sys.argv[1];batch=sys.argv[2]
old=json.loads((R/'run_r24'/f'{batch}_results.json').read_text(encoding='utf8'))
before={(r['document']['source_id'],u['start'],u['end']):u for r in old for u in r['semantic_partition']}
records=[]
for f in (R/f'run_{version}'/'sources').glob('*.json'):
    r=json.loads(f.read_text(encoding='utf8'))['result'];sid=r['document']['source_id']
    if not any(d['document']['source_id']==sid for d in old):continue
    for u in r['semantic_partition']:
        previous=before.get((sid,u['start'],u['end']))
        if not previous:continue
        if previous.get('practice')!=u.get('practice') or previous.get('deliver')!=u.get('deliver'):
            records.append({'source_id':sid,'index':u['index'],'raw':u['text'],'old':previous.get('practice'),
             'new':u.get('practice'),'deliver':u['deliver'],'fallback':u.get('summary_fallback'),
             'initial_issues':u.get('summary_fidelity_audit',{}).get('initial',{}).get('issues')})
print(json.dumps(records,ensure_ascii=False,indent=2))
