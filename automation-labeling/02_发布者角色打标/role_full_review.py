import json,sys
from pathlib import Path
base=Path('D:/Codex/outputs/01a1349d-c76e-7b63-be36-3c8e0766deef/20261014_发布者角色各50条盲测')
old={p['sample_id']:p for p in json.loads((base/'packets.json').read_text(encoding='utf-8'))}
full=json.loads(Path(str(base)+'_全文复测/packets.json').read_text(encoding='utf-8'))
mode=sys.argv[1]
for p in full:
 if len(sys.argv)>2 and p['sample_id'] not in sys.argv[2:]:continue
 f=p['fields'];prior=old[p['sample_id']]['fields']
 changes={k:v[len(prior[k]):] for k,v in f.items() if v!=prior[k]}
 if mode=='tail' and not changes:continue
 print(json.dumps({'id':p['sample_id'],'name':f['作者名字'],'title':f['文章标题'],'fields':changes if mode=='tail' else f},ensure_ascii=False))
