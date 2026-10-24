import json
from pathlib import Path
out=Path('D:/Codex/outputs/01a1349d-c76e-7b63-be36-3c8e0766deef/20261014_发布者角色各50条盲测')
results=json.loads((out/'qwen_results.json').read_text(encoding='utf-8'))
packets={p['sample_id']:p for p in json.loads((out/'packets.json').read_text(encoding='utf-8'))}
normalized=[]
for r in results:
 if r['response']:continue
 a=next((a for a in reversed(r['attempts']) if a.get('raw_response')),None)
 if not a:continue
 v=a['raw_response'];raw_role=v.get('role')
 if raw_role not in ['品牌','区域公司','项目官方']:continue
 if not isinstance(v.get('reason'),str) or not isinstance(v.get('evidence'),list) or not isinstance(v.get('review_required'),bool):continue
 v=dict(v);v['role']='品牌、区域公司、项目官方'
 r['response']=v;r['normalized_role_from']=raw_role;r['validation_issues']=[]
 f=packets[r['sample_id']]['fields']
 for e in v['evidence']:
  if not isinstance(e,dict) or not e.get('quote') or e.get('field') not in f or e['quote'] not in f[e['field']]:r['validation_issues'].append('证据无法逐字定位')
 if not v['evidence']:r['validation_issues'].append('明确角色缺证据')
 normalized.append({'sample_id':r['sample_id'],'raw_role':raw_role,'canonical_role':v['role']})
(out/'qwen_results_normalized.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
(out/'normalization.json').write_text(json.dumps(normalized,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'normalized':normalized,'valid_decisions':sum(bool(r['response']) for r in results)},ensure_ascii=False,indent=2))
