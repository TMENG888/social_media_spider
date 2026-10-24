import csv,json,random,hashlib
from pathlib import Path
from collections import Counter
src=Path(r'C:/Users/YS-Insight/Desktop/ods_social_media_post_peking.csv')
out=Path(r'D:/Codex/outputs/01a1349d-c76e-7b63-be36-3c8e0766deef/20261013_各平台广告盲测50条')
out.mkdir(parents=True,exist_ok=True)
fields=['作者名字','文章标题','文章内容','文章标签','文章图片信息','文章视频内容']
with src.open(encoding='utf-8-sig',newline='') as f:
 rows=[dict(r,source_row=i) for i,r in enumerate(csv.DictReader(f),2)]
rng=random.Random(20261013)
samples=[]
for platform in sorted({r['平台'] for r in rows}):
 for r in rng.sample([r for r in rows if r['平台']==platform],10):
  samples.append(r)
packets=[dict(sample_id=f'S{i:03}',platform=r['平台'],source_row=r['source_row'],fields={k:r.get(k,'') for k in fields}) for i,r in enumerate(samples,1)]
manifest={'source':str(src),'sha256':hashlib.sha256(src.read_bytes()).hexdigest(),'seed':20261013,'counts':dict(Counter(r['平台'] for r in rows)),'sample_count':len(samples),'hidden_fields':['是否广告','广告关键词','清洗标注','分类','文章标注','关键词','项目','地点','内容类型'],'max_cell_length':max(len(str(v)) for r in samples for v in r.values())}
for name,data in [('manifest',manifest),('raw_samples',samples),('blind_packets',packets)]:
 (out/f'{name}.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(manifest,ensure_ascii=False))
for p in packets: print(p['sample_id'],p['platform'],p['source_row'],sum(len(x) for x in p['fields'].values()))
