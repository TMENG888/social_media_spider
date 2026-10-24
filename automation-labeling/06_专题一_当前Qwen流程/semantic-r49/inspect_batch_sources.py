"""Read-only source/annotation inspection; never imported by model runners."""
import json,sys
from pathlib import Path
sys.stdout.reconfigure(encoding='utf8')
R=Path(__file__).parent
version=sys.argv[1];wanted=set(sys.argv[2:])
tax={t['tag_id']:'/'.join(filter(None,[t['l2'],t['l3'],t['l4'],t['l5']])) for t in json.loads((R/'inputs/taxonomy.json').read_text(encoding='utf8'))}
for file in sorted((R/'batch300'/version/'sources').glob('*.json')):
 d=json.loads(file.read_text(encoding='utf8'))['result'];sid=d['document']['source_id']
 if wanted and sid not in wanted:continue
 print(json.dumps({'source_id':sid,'title':d['document']['row'].get('文章标题'),'role':d['publisher_role']},ensure_ascii=False))
 rows={(r['起点'],r['终点']):r for r in d['rows']}
 for u in d['semantic_partition']:
  row=rows.get((u['start'],u['end']),{})
  print(json.dumps({'index':u['index'],'deliver':u['deliver'],'raw':u['text'],'practice':u.get('practice'),'brand':row.get('品牌组'),'entity':row.get('经营主体'),'city':row.get('城市'),'project':u.get('project'),'labels':[{'id':p['tag_id'],'path':tax[p['tag_id']],'quote':p['quote'],'reason':p['reason']} for p in u['labels']]},ensure_ascii=False))
