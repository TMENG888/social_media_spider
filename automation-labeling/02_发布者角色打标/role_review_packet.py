import json,sys
from pathlib import Path
ps=json.loads(Path('D:/Codex/outputs/01a1349d-c76e-7b63-be36-3c8e0766deef/20261014_发布者角色各50条盲测/packets.json').read_text(encoding='utf-8'))
start=int(sys.argv[1]);end=int(sys.argv[2])
for p in ps[start:end]:
 f=p['fields']
 print(json.dumps({'sid':p['sample_id'],'platform':f['平台'],'name':f['作者名字'],'title':f['文章标题'],'body':f['文章内容'][:450],'transcript':f['文章视频内容'][:350],'tags':f['文章标签']},ensure_ascii=False))
