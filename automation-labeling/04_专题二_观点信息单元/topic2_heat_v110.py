"""Read-only missing-heat backfill, matching 热度_互动指标计算.sql.

No model calls, database writes or source/checkpoint edits. Rank the complete
two-topic article snapshot, never the selected labeling batch.
"""
import copy,csv,hashlib,math,re,statistics
from collections import defaultdict
from datetime import datetime,timezone
from decimal import Decimal,ROUND_HALF_UP,localcontext
from pathlib import Path

VERSION='topic2-heat-missing-v110'
TOPICS=('全国地产设计产品力监测','北京臻澐项目口碑')
FIELDS=('文章点赞数','文章收藏数','文章分享数','文章评论数')
WEIGHTS=tuple(map(Decimal,('0.27','0.27','0.26','0.20')))
DEFAULT_FILES=tuple(Path('C:/Users/YS-Insight/Desktop/专题数据')/n for n in
 ('ods_social_media_post_01.csv','ods_social_media_post_02.csv'))
SQL=Path(__file__).resolve().parents[1]/'sql/heat-interaction.sql'
_COUNT=re.compile(r'^[-+]?[0-9]+([.][0-9]+)?$')

def existing_heat(value):
 if value is None or (isinstance(value,str) and not value.strip()):return None
 if isinstance(value,bool):raise ValueError('Invalid boolean heat')
 try:v=float(value)
 except (ValueError,TypeError):raise ValueError('Invalid existing heat') from None
 if not math.isfinite(v) or not 0<=v<=100:raise ValueError('Existing heat outside [0,100]')
 return v

def count_value(value):
 text=str(value).strip() if value is not None else ''
 if not _COUNT.fullmatch(text):return None
 with localcontext() as ctx:
  ctx.prec=50
  v=Decimal(text).quantize(Decimal('.000001'),rounding=ROUND_HALF_UP)
  if abs(v)>=Decimal(10)**24:raise ValueError('Count overflows SQL DECIMAL(30,6)')
  return max(v,Decimal(0))

def group_key(row):
 return (row.get('平台') or '未标明平台',row.get('内容类型') or '未标明类型')

def calculate(rows):
 """Pure full-snapshot calculator; IDs must be unique ODS article primary keys."""
 by={};groups=defaultdict(list)
 for row in rows:
  if row.get('项目') not in TOPICS:continue
  pid=str(row['id'])
  if not pid or pid in by:raise ValueError('Missing/duplicate ODS article ID in heat baseline')
  by[pid]=row;groups[group_key(row)].append(pid)
 scores={pid:None for pid in by};row_audit={};group_audit=[]
 for key,ids in groups.items():
  parts=defaultdict(list);stats=[]
  for field,weight in zip(FIELDS,WEIGHTS):
   vals=[(count_value(by[pid].get(field)),pid) for pid in ids]
   vals=sorted((v,pid) for v,pid in vals if v is not None)
   n=len(vals);distinct=len({v for v,pid in vals})
   stat={'field':field,'valid_n':n,'unique_n':distinct,'usable':n>=5 and distinct>1 and vals[-1][0]>0}
   stats.append(stat)
   if not stat['usable']:continue
   # PERCENTILE_CONT(0.995), followed by LN(1+LEAST(v,cap)).
   position=Decimal(n-1)*Decimal('.995');lo=int(position);hi=math.ceil(position)
   cap=vals[lo][0]+(vals[hi][0]-vals[lo][0])*(position-lo)
   stat['cap_p995']=str(cap)
   ranked=sorted((math.log1p(float(min(v,cap))),pid) for v,pid in vals)
   i=0
   while i<n:
    j=i+1
    while j<n and ranked[j][0]==ranked[i][0]:j+=1
    # 1-based average rank / valid metric n; not percent_rank or cume_dist.
    q=Decimal(i+1+j)/Decimal(2*n)
    for z,pid in ranked[i:j]:parts[pid].append((field,weight,q))
    i=j
  for pid in ids:
   ps=parts[pid]
   if len(ps)>=2:
    score=100*sum(w*q for f,w,q in ps)/sum(w for f,w,q in ps)
    scores[pid]=float(score.quantize(Decimal('.01'),rounding=ROUND_HALF_UP))
   row_audit[pid]={'available_metrics':[f for f,w,q in ps],
    'percentiles':{f:str(q) for f,w,q in ps},'calculated_heat':scores[pid],
    'reason':'计算成功' if scores[pid] is not None else '不足两项可用互动指标；单项须至少5个有效值、非恒定且最大值大于0'}
  group_audit.append({'platform':key[0],'content_type':key[1],'rows':len(ids),'metrics':stats})
 return scores,row_audit,group_audit

def file_sha(path):
 h=hashlib.sha256()
 with Path(path).open('rb') as stream:
  for block in iter(lambda:stream.read(1024*1024),b''):h.update(block)
 return h.hexdigest()

class HeatResolver:
 """Lazy immutable baseline per aggregation run. Explicit files for fresh exports."""
 def __init__(self,files=None):
  self.files=tuple(Path(p) for p in (DEFAULT_FILES if files is None else files))
  self.ready=False;self.parents={};self.resolved={}
  self.audit={'version':VERSION,'scope':'两专题全量文章；按平台＋内容类型排名；仅补缺，不写业务数据',
   'loaded_at_utc':None,'inputs':[],'groups':[],'parents':[]}

 def load(self):
  if self.ready:return
  if not self.files:raise ValueError('A complete two-topic article baseline is required')
  rows=[];topics=set()
  csv.field_size_limit(10000000)
  for path in self.files:
   if not path.is_file():raise FileNotFoundError(f'Missing heat baseline: {path}')
   before=path.stat();sha=file_sha(path)
   with path.open(encoding='utf-8-sig',newline='') as stream:
    reader=csv.DictReader(stream)
    required={'id','项目','平台','内容类型',*FIELDS}
    if not required<=set(reader.fieldnames or []):raise ValueError(f'Incomplete baseline columns: {path}')
    selected=[r for r in reader if r['项目'] in TOPICS]
   after=path.stat()
   if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns) or file_sha(path)!=sha:
    raise ValueError('Heat baseline changed during reading; retry with a stable snapshot')
   rows.extend(selected);topics.update(r['项目'] for r in selected)
   self.audit['inputs'].append({'path':str(path.resolve()),'sha256':sha,'rows':len(selected),'mtime_utc':datetime.fromtimestamp(after.st_mtime,timezone.utc).isoformat()})
  if topics!=set(TOPICS):raise ValueError('Heat baseline must contain both collection topics, not the labeling sample')
  self.scores,self.details,self.audit['groups']=calculate(rows)
  self.parents={str(r['id']):r for r in rows}
  self.audit.update(loaded_at_utc=datetime.now(timezone.utc).isoformat(),baseline_rows=len(rows),
   formula_sql={'path':str(SQL),'sha256':file_sha(SQL) if SQL.is_file() else None})
  self.ready=True

 def resolve(self,parent_id,value=None,*,parent_row=None):
  pid=str(parent_id);prior=existing_heat(value)
  if pid in self.resolved:
   result=self.resolved[pid]
   if prior is not None and prior!=result:raise ValueError('Conflicting heat for same parent article')
   return result
  if prior is not None:
   self.resolved[pid]=prior;self.audit['parents'].append({'parent_id':pid,'status':'preserved','heat':prior});return prior
  self.load()
  if pid not in self.parents:raise ValueError(f'Parent article absent from full heat baseline: {pid}')
  raw=self.parents[pid]
  if parent_row is not None:
   if str(parent_row.get('id'))!=pid:raise ValueError('Parent identity mismatch')
   for field in ('平台','内容类型','项目',*FIELDS):
    if field in parent_row and parent_row[field]!=raw.get(field):
     raise ValueError(f'Parent inputs differ from heat snapshot: {pid}/{field}')
  # A fresh snapshot may already contain the score missing in an older cache.
  snapshot=existing_heat(raw.get('热度指数'))
  result=snapshot if snapshot is not None else self.scores[pid]
  self.resolved[pid]=result
  self.audit['parents'].append({'parent_id':pid,'status':'snapshot_existing' if snapshot is not None else ('filled' if result is not None else 'unavailable'),
   'heat':result,**self.details[pid]})
  return result

def backfill_payload(payload,*,files=None):
 """Codex adapter: synchronize missing source/unit heat before rebuilding metrics."""
 x=copy.deepcopy(payload);resolver=HeatResolver(files if files is not None else x.get('heat_baseline_files'))
 byparent=defaultdict(list)
 for source in x['sources']:byparent[str(source['parent_id'])].append(source)
 byrecord={s['record_id']:s for s in x['sources']};units_by_parent=defaultdict(list)
 for u in x['units']:
  if u['record_id'] not in byrecord:raise ValueError('Heat unit has unknown source')
  source=byrecord[u['record_id']]
  if str(u['父文章ODS主键'])!=str(source['parent_id']):raise ValueError('Heat parent relation mismatch')
  units_by_parent[str(source['parent_id'])].append(u)
 for pid,sources in byparent.items():
  units=units_by_parent[pid]
  known={v for raw in [s.get('heat') for s in sources]+[u.get('热度指数') for u in units] if (v:=existing_heat(raw)) is not None}
  if len(known)>1:raise ValueError('Conflicting existing source/unit heat; do not overwrite')
  result=resolver.resolve(pid,next(iter(known)) if known else None)
  for s in sources:s['heat']=result
  for u in units:u['热度指数']=result
 previous=x.get('heat_backfill_audit')
 if previous and all(a['status']=='preserved' for a in resolver.audit['parents']):
  x['heat_backfill_audit']=previous
 else:
  x['heat_backfill_audit']=resolver.audit
 return x

def refresh_payload_heat(payload,*,files=None):
 """Export guard for cached Codex/Qwen payloads; change heat, not labels/enums.

 Existing pair/row order is retained so worksheet formula ranges remain valid.
 """
 x=backfill_payload(payload,files=files)
 parents={str(s['parent_id']):s['heat'] for s in x['sources']}
 grouped=defaultdict(dict)
 for row in x['heat_rows']:
  pid=str(row['parent_id'])
  if pid not in parents:raise ValueError('Heat worksheet parent has no selected source')
  row['heat']=parents[pid];grouped[row['group'],row['tag_id']][pid]=row['heat']
 for metric in x['metrics']:
  values=list(grouped[metric['group'],metric['tag_id']].values())
  valid=[v for v in values if v is not None]
  metric.update(heat=statistics.median(valid) if valid else None,heatN=len(valid),missingHeat=len(values)-len(valid))
 for channel in x['channels']:
  channel['heat_sources']=sum(s['heat'] is not None for s in x['sources'] if s['platform']==channel['platform'] and s['kind']==channel['kind'])
 return x
