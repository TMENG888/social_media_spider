import json
from pathlib import Path
import delivery_v87 as v
base=v.base
ROOT=Path('C:/Users/YS-Insight/Documents/Codex/2026-09-24/new-chat/outputs/01a0d182-286c-72b2-8ec2-0f2b91c5a8c9/20261010_保守纠错双表交付')
if __name__=='__main__':
 p=json.loads((ROOT/'delivery_results.json').read_text(encoding='utf-8'))
 tax=base.load_taxonomy(v.earlier.support.previous.p.p.v.legacy.TAXONOMY)
 print('LABELS',json.dumps([t for t in tax if any(s in str(t) for s in ['归家','动线','泳池','地铁','产权','物业配套','规模与风格'])],ensure_ascii=False))
 for r in p['results']:
  if r['document']['record_id'] in ['T1-75149','T1-75303','T1-75447','T1-2467985060850735035','T1-3968354797766124687','T2-1263114957749348749']:
   print('SOURCE',r['document']['record_id'],r['document']['text'])
   print('UNITS',json.dumps([{'id':u['unit_id'],'quote':u.get('原文摘录',u.get('原始摘录')),'tags':[t['标签路径ID'] for t in u['标签明细']],'prose':u.get('具体产品做法',u.get('观点摘要'))} for u in r['rows']],ensure_ascii=False))
 print('STATS',json.dumps({'sources':len(p['results']),'empty_label':sum(not u['标签明细'] for r in p['results'] for u in r['rows']),'empty_prose':sum(not u.get('具体产品做法',u.get('观点摘要')) for r in p['results'] for u in r['rows']),'empty_reasons':sum(not u.get('打标说明') for r in p['results'] for u in r['rows'])},ensure_ascii=False))
