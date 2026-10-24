import csv,json,random,hashlib,sys
from pathlib import Path
from collections import Counter,defaultdict
base=Path('D:/Codex/outputs/01a1349d-c76e-7b63-be36-3c8e0766deef/20261014_发布者角色各50条盲测')
full='--legacy-truncated' not in sys.argv
out=Path(str(base)+'_全文复测') if full else base
out.mkdir(exist_ok=True)
if (out/'reference_freeze.json').exists():raise RuntimeError('Frozen run exists; preparation cannot overwrite it')
sources=[('专题一','C:/Users/YS-Insight/Desktop/专题数据/ods_social_media_post_01.csv'),('专题二','C:/Users/YS-Insight/Desktop/ods_social_media_post_peking.csv')]
packets=[];raw=[];manifest=[]
for di,(name,src) in enumerate(sources):
 with open(src,encoding='utf-8-sig',newline='') as f:rows=list(csv.DictReader(f))
 groups=defaultdict(list)
 for idx,r in enumerate(rows):groups[r.get('平台') or '平台缺失'].append((idx+2,r))
 rng=random.Random(20261014+di);selected=[];allocation={k:0 for k in sorted(groups)}
 while len(selected)<50:
  for k in sorted(groups):
   if len(selected)>=50:break
   if allocation[k]<len(groups[k]):allocation[k]+=1;selected.append(k)
 chosen=[]
 for k,n in allocation.items():chosen.extend(rng.sample(groups[k],n))
 for i,(line,r) in enumerate(chosen,1):
  sid=f'{di+1}-{i:02}'
  # Identical text fields for both annotators; full-text mode never slices strings.
  fields={k:r.get(k) or '' for k in ['平台','作者名字','作者主页链接','文章标题','文章标签']}
  trunc=[]
  for k,limit in [('文章内容',1800),('文章视频内容',1200),('文章图片信息',600)]:
   v=r.get(k) or '';fields[k]=v if full else v[:limit]
   if not full and len(v)>limit:trunc.append(k)
  packets.append({'sample_id':sid,'dataset':name,'fields':fields,'truncated_fields':trunc})
  raw.append({'sample_id':sid,'dataset':name,'source_line':line,'row':r})
 manifest.append({'dataset':name,'source':src,'sha256':hashlib.sha256(Path(src).read_bytes()).hexdigest(),'total':len(rows),'seed':20261014+di,'platform_counts':dict(Counter(r.get('平台') for r in rows)),'sample_platform_counts':allocation})
if full:
 prior=json.loads((base/'raw_samples.json').read_text(encoding='utf-8'))
 if raw!=prior:raise RuntimeError('Sample identities or raw content changed; stop')
 audit=[]
 for p,rr in zip(packets,raw):
  source=rr['row'];checks=[]
  for k,v in p['fields'].items():
   assert v==(source.get(k) or '')
   checks.append({'field':k,'chars':len(v),'sha256':hashlib.sha256(v.encode('utf-8')).hexdigest(),'exact_source_match':True})
  audit.append({'sample_id':p['sample_id'],'id':source['id'],'article_id':source['文章id'],'fields':checks,'no_truncation':not p['truncated_fields']})
 (out/'full_input_audit.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2),encoding='utf-8')
for filename,data in [('packets.json',packets),('raw_samples.json',raw),('manifest.json',manifest)]:
 (out/filename).write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(manifest,ensure_ascii=False,indent=2))
