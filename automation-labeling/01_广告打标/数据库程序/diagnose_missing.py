import csv,json
from pathlib import Path
from collections import Counter,defaultdict
root=Path(r'D:/Codex/outputs/01a1349d-c76e-7b63-be36-3c8e0766deef/20261013_北京臻澐口碑数据库广告打标')
src=Path(r'C:/Users/YS-Insight/Desktop/ods_social_media_post_peking.csv')
with src.open(encoding='utf-8-sig',newline='') as f:rows=list(csv.DictReader(f))
commits=[json.loads(x) for x in (root/'committed_updates.jsonl').read_text(encoding='utf-8').splitlines() if x.strip()]
by_id={x['id']:x for x in commits}
snap=json.loads(sorted(root.glob('before_snapshot_*.json'))[-1].read_text(encoding='utf-8'))['rows']
snapshot_id={str(x['id']):x for x in snap}
snapshot_key=defaultdict(list)
for r in snap:snapshot_key[(str(r.get('文章id') or ''),r.get('平台'),r.get('项目'))].append(r)
fields=['平台','作者名字','文章标题','文章内容','文章标签','文章图片信息','文章视频内容']
target=[r for r in rows if r.get('项目')=='北京臻澐项目口碑']
blank=lambda v:not v or not str(v).strip() or str(v).strip().lower() in ('null','\\n')
missing=[r for r in target if blank(r.get('是否广告'))]
categories=Counter();details=[]
for r in missing:
 old=snapshot_id.get(r['id']);method='id'
 if old and (str(old.get('文章id') or ''),old.get('平台'))!=(r.get('文章id'),r.get('平台')):old=None
 if not old:
  candidates=snapshot_key[(r.get('文章id'),r.get('平台'),r.get('项目'))]
  if len(candidates)==1:old=candidates[0];method='unique article key'
 changed=[f for f in fields if str(r.get(f) or '')!=str((old or {}).get(f) or '')] if old else []
 c=by_id.get(str(old['id'])) if old else None
 category='previously_committed_now_blank' if c else 'not_in_original_committed_set'
 categories[category]+=1
 details.append({'id':r['id'],'article_id':r.get('文章id'),'platform':r.get('平台'),'author':r.get('作者名字'),'title':r.get('文章标题'),'csv_blank_value':r.get('是否广告'),'previous_label':c['after'] if c else None,'match_method':method if old else None,'input_changed_fields':changed,'old_fetch_time':old.get('文章获取时间') if old else None,'new_fetch_time':r.get('文章获取时间'),'committed_at':c.get('time') if c else None})
label_changes=[]
for r in target:
 old=snapshot_id.get(r['id']);c=by_id.get(r['id'])
 if old and c and not blank(r.get('是否广告')) and r.get('是否广告')!=c['after']:label_changes.append(r['id'])
print(json.dumps({'csv_total':len(rows),'projects':dict(Counter(r.get('项目') for r in rows)),'target_total':len(target),'labels':dict(Counter(r.get('是否广告') for r in target)),'missing_by_platform':dict(Counter(r.get('平台') for r in missing)),'missing_categories':dict(categories),'matched_inputs_unchanged':sum(not r['input_changed_fields'] for r in details if r['previous_label']),'matched_inputs_changed':sum(bool(r['input_changed_fields']) for r in details if r['previous_label']),'nonempty_label_changed_count':len(label_changes),'examples':details[:15]},ensure_ascii=False,indent=2))
