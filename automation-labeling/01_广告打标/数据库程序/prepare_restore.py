import csv, json
from pathlib import Path

root = Path('D:/Codex/outputs/01a1349d-c76e-7b63-be36-3c8e0766deef/20261013_北京臻澐口碑数据库广告打标')
out = root / 'restore_20261014_247'
fields = ['平台','作者名字','文章标题','文章内容','文章标签','文章图片信息','文章视频内容']
with Path('C:/Users/YS-Insight/Desktop/ods_social_media_post_peking.csv').open(encoding='utf-8-sig', newline='') as f:
    rows = list(csv.DictReader(f))
snapshot = json.loads((root / 'before_snapshot_2026-10-13T10-51-37.876Z.json').read_text(encoding='utf-8'))['rows']
old = {str(r['id']): r for r in snapshot}
commits = {}
for line in (root/'committed_updates.jsonl').read_text(encoding='utf-8').splitlines():
    c = json.loads(line)
    if c['id'] in commits:
        raise ValueError('Duplicate committed ID')
    commits[c['id']] = c
if len({r['id'] for r in rows}) != len(rows):
    raise ValueError('Duplicate CSV ID')
selected = []
for r in rows:
    s = old.get(r['id']); c = commits.get(r['id'])
    if r.get('项目') != '北京臻澐项目口碑' or (r.get('是否广告') or '').strip() or not s or not c:
        continue
    if any(str(r.get(f) or '') != str(s.get(f) or '') for f in ['文章id','项目',*fields]):
        continue
    selected.append({'id':r['id'],'article_id':r['文章id'],'project':r['项目'],'platform':r['平台'],
                     'input':{f:r.get(f) or '' for f in fields},'commit':c})
if len(selected) != 247:
    raise ValueError(f'Expected exactly 247; found {len(selected)}. Stop for review.')
out.mkdir(exist_ok=True)
p = out/'candidates.json'
if p.exists():
    if json.loads(p.read_text(encoding='utf-8')) != selected:
        raise ValueError('Candidate manifest already exists with different contents')
else:
    p.write_text(json.dumps(selected,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'candidate_count':len(selected),'labels':{k:sum(r['commit']['after']==k for r in selected) for k in ['是','否']},'manifest':str(p)},ensure_ascii=False))
