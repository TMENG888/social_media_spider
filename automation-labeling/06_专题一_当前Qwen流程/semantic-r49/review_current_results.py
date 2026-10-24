"""Read-only semantic review view; never imported by inference runners."""
import json, sys
from pathlib import Path
sys.stdout.reconfigure(encoding='utf8')
root=Path(__file__).parent
version,batch,*ids=sys.argv[1:]
taxonomy={x['tag_id']:x for x in json.loads((root/'inputs/taxonomy.json').read_text(encoding='utf8'))}
results=json.loads((root/f'run_{version}/{batch}_results.json').read_text(encoding='utf8'))
for r in results:
    sid=r['document']['source_id']
    if ids and sid not in ids: continue
    print('\nSOURCE',sid,r['document']['title'])
    for p in r['semantic_partition']:
        print('SLICE',p['index'],p['start'],p['end'],'DELIVER',p['deliver'])
        print('RAW',p['text'])
        if p['deliver']:
            print('IDENTITY',p.get('brand'),p.get('entity'),p.get('city'))
            print('SUMMARY',p.get('practice'))
        for t in p['labels']:
            tax=taxonomy[t['tag_id']]
            path='/'.join(str(tax[k] or '') for k in ['l1','l2','l3','l4','l5'])
            print('TAG',t['tag_id'],path,'PROOF',t['quote'])
