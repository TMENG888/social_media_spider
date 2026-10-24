"""Raw-source corroboration only, never reads reference labels or frozen answers."""
import csv,re,json,functools
from pathlib import Path
import topic1_semantic_pipeline as pipe
RAW=Path('C:/Users/YS-Insight/Desktop/专题数据/ods_social_media_post_01.csv')
FIELDS=['文章标题','文章标签','文章内容','文章视频内容']
def norm(x):
 return re.sub(r'[^0-9a-z\u4e00-\u9fff]','',str(x).lower().translate(str.maketrans('華雲號臺萬','华云号台万')))
@functools.lru_cache(maxsize=1)
def source_index():
 with RAW.open(encoding='utf-8-sig',newline='') as f:rows=list(csv.DictReader(f))
 return [(r,norm(' '.join(r.get(k,'') for k in FIELDS))) for r in rows]
def evidence_candidates(doc,units,business):
 entities=sorted({r['经营主体'] for r in business['rows'] if r.get('经营主体')})
 queries={norm(u.get('project','')) for u in units if u.get('project')}
 queries={q for q in queries if len(q)>=3}
 # Brand punctuation aliases are normalised only for retrieval. Evidence is
 # always quoted from untouched source fields, not from normalised text.
 out=[{'source_id':doc['source_id'],'url':doc['row'].get('文章链接'),'fields':{k:doc['row'].get(k,'') for k in FIELDS}}]
 ranked=[]
 for r,t in source_index():
  if str(r['id'])==doc['source_id']:continue
  hits=[q for q in queries if q in t]
  if not hits:continue
  explicit=[e for e in entities if any(e in r.get(k,'') for k in FIELDS)]
  if not explicit:continue
  fields={'文章标题':r.get('文章标题',''),'文章标签':r.get('文章标签','')}
  for k in ['文章内容','文章视频内容']:
   raw=r.get(k,'');clips=[]
   for e in explicit:
    i=raw.find(e)
    if i>=0:clips.append(raw[max(0,i-100):min(len(raw),i+180)])
   if clips:fields[k]=clips
  ranked.append((max(map(len,hits)),len(explicit),{'source_id':str(r['id']),'url':r.get('文章链接'),'fields':fields}))
 ranked.sort(key=lambda x:(-x[0],-x[1],x[2]['source_id']))
 out.extend(x[2] for x in ranked[:12]);return out
SYSTEM=pipe.BASE+'''
只核对身份元数据，不标产品标签，不受上一步的拟定值束缚。经营主体遵循：本文明示优先→完整字典产品系/别名仅辅助候选→同城同盘具体来源核实→不能确定留空。
给出的外部候选是检索结果而非已确认映射。不得跨城市同名盘误传；不同住宅或同文对比对象不是本片。一个案名含安/和/天等单字不足以命中产品系。不能凭品牌猜主体，不能把项目公司直接上推集团。
来源标题/文章标签可作为本篇同盘身份依据。只核实本片真实住宅对象。每个填入值必须有原文证据；主体须有同盘来源明示完整主体名。城市也须有来源支持，不从地理常识猜测。
发布者角色不看账号名字猜机构，缺可核实身份证据用身份不明。普通账号也不能仅因缺机构证据自动判。
返回JSON {"publisher_role":"身份不明","publisher_evidence":[],"units":[{"index":1,"brand":"","entity":"","city":"","proofs":[{"source_id":"","field":"文章标题","quote":"原文连续证据"}],"reason":"采用或留空的具体原因"}]}。
每个index必须返回。仅身份查询结果写入这些字段，不从外部候选增添产品配置或打标结果。'''
def process_legacy(result,business,runner):
 doc=result['document'];units=[u for u in result['semantic_partition'] if u['deliver']]
 candidates=evidence_candidates(doc,units,business)
 names={u['project'] for u in units if u.get('project')}
 if len(names)==1:
  only=next(iter(names))
  for u in units:
   if not u.get('project'):u['project']=only
 groups={}
 for u in units:groups.setdefault(u.get('project',''),[]).append(u)
 answers={};role='身份不明';role_proofs=[]
 for name,group in groups.items():
  payload={'target_project':name,'source':{'text':doc['text'],'metadata':pipe.metadata(doc)},'business_dictionary':business,'source_candidates':candidates}
  answer=pipe.call(runner,doc,'''核对指定住宅项目的品牌、具体经营主体及城市，只做身份，不做产品标签。原文明示优先，产品系字典只作候选，需候选来源证明同城同盘。外部候选不是已核实答案；跨城同名、不同项目、项目公司无集团关联不使用。品牌不等于主体；未知留空。
品牌/城市可用本文标题、正文和文章标签的明确证据。经营主体必须有同盘来源直接写出该主体名称，不能凭案名中的普通字或集团品牌推断。只在正文/资质有身份凭据时判官方或专业机构；不能凭作者名字判角色，未知用身份不明。
返回一个JSON对象，不要units数组：{"brand":"","entity":"","city":"","proofs":[{"source_id":"","field":"文章标题或文章内容或文章标签或文章视频内容","quote":"尽量短的连续原文证据，不加省略号、不改空格"}],"reason":"一句话采用或留空理由","publisher_role":"身份不明","publisher_evidence":[]}。
''',payload,'专题一单项目身份核实')
  if not isinstance(answer.get('proofs'),list):raise ValueError('Missing identity proof list')
  for u in group:answers[u['index']]=answer
  role=answer.get('publisher_role','身份不明');role_proofs=answer.get('publisher_evidence',[])
 by={u['index']:u for u in units}
 sources={c['source_id']:c for c in candidates};entity_brand={x['经营主体']:x['品牌组'] for x in business['rows'] if x.get('经营主体')}
 audit=[]
 for index,u in by.items():
  a=answers[index];valid=[];errors=[]
  for e in a.get('proofs',[]):
   raw=sources.get(str(e.get('source_id')),{}).get('fields',{}).get(e.get('field'),'');raws=raw if isinstance(raw,list) else [raw]
   if e.get('quote') and any(e['quote'] in v for v in raws):valid.append(e)
   else:errors.append('非原文连续身份引文')
  ent=a.get('entity') or '';brand=a.get('brand') or '';city=a.get('city') or ''
  if ent and (ent not in entity_brand or not any(ent in e['quote'] for e in valid) or entity_brand[ent]!=brand):errors.append('主体缺明示证据或品牌不匹配');ent=''
  if city and not any(city in e['quote'] for e in valid):errors.append('城市缺明确引文');city=''
  # Brand may be explicitly substantiated by a verified legal entity.
  if brand and not (any(brand in e['quote'] for e in valid) or ent):errors.append('品牌缺明确引文');brand=''
  u['brand']=brand;u['entity']=ent;u['city']=city
  note=a.get('reason','')+('；身份核验：'+'、'.join(errors) if errors else '')
  row=next(row for row in result['rows'] if row['起点']==u['start'] and row['终点']==u['end'])
  row.update({'品牌组':brand,'经营主体':ent,'城市':city,'备注':(row.get('备注','')+'；'+note).strip('；')})
  audit.append({'index':index,'proofs':valid,'errors':errors,'reason':note})
 valid_role=[]
 for e in role_proofs:
  if not isinstance(e,dict) or e.get('field')=='作者名字':continue
  raw=doc['row'].get(e.get('field'),'')
  if e.get('quote') and e['quote'] in raw:valid_role.append(e)
 if role not in pipe.ROLES or not valid_role:role='身份不明'
 for row in result['rows']:row['发布者角色']=role
 result.update({'publisher_role':role,'identity_audit':audit,'identity_candidates':candidates,'publisher_identity_proofs':valid_role})
 return result

IDENTITY_GRID='''你是住宅项目身份核验员，只核对指定住宅的品牌组、经营主体、城市和发布者角色，不做产品标注。
证据表每行是未经改写的原始字段短段。只选证据ID，不重写引文。证据表中的外部记录只是检索候选，并未核实同盘；标题、城市、案名/别名和开发或代建关系须同时核对，跨城同名或对比对象不可使用。原始标题及标签可佐证本篇身份。
品牌可由本篇明确的同盘品牌或已核实主体确认。城市只能按明确文本确认。经营主体是品牌字典中的经营主体枚举，不是任意项目公司：证据明确“某经营主体旗下某项目公司开发该盘”可确认；只给项目公司且没有集团关联时不能上推。集团品牌不等于经营主体；产品系及别名仅产生候选，不能因单字相似确认。
主体可以通过本篇明示，或已确认同城同盘候选原文直接明示来补齐；不要仅看本篇没有主体就忽略外部同盘证据。有明确证据则填，没有则空。不得把“需要具体项目公司全称”误当为经营主体枚举要求。
发布者角色不能凭账号名字猜；原文中真实身份、组织资质或正式身份说明才可用，营销口吻和买房咨询口吻均不足。无证据为身份不明。
返回JSON {"brand":{"value":"","evidence_ids":[]},"entity":{"value":"","evidence_ids":[]},"city":{"value":"","evidence_ids":[]},"publisher_role":{"value":"身份不明","evidence_ids":[]},"same_project_reason":"说明同盘关联及采用/留空原因"}。
每个非空value选有依据的证据ID，可以跨本篇的标题与正文共同证明同盘身份。entity的value只能从allowed_entities选择，证据须明示该经营主体；不要返回项目公司全称来代替。证据不足空value和空数组。只输出JSON。'''

def evidence_grid(candidates):
 rows=[]
 for c in candidates:
  for field,raw in c['fields'].items():
   for clip in raw if isinstance(raw,list) else [raw]:
    if not clip:continue
    # Nonsemantic evidence addresses only. Keep original text untouched.
    # Long sentences are windows so the model selects IDs, not retypes quotes.
    for m in re.finditer(r'.{1,120}?(?:[。！？!?\n]|$)|.{120}',clip,re.S):
     rows.append({'id':len(rows)+1,'source_id':str(c['source_id']),'field':field,'quote':m.group(),'url':c.get('url'),'is_current_source':c is candidates[0]})
 return rows

def scoped_identity_proofs(project,city,field,proofs,candidates,source_id):
 """Retain relevant source proofs, not an unverified free-text alias claim."""
 target=norm(project);accepted=[];discarded=[]
 for sid in {e['source_id'] for e in proofs}:
  rows=[e for e in proofs if e['source_id']==sid]
  current=sid==str(source_id)
  candidate=next((c for c in candidates if str(c['source_id'])==sid),None)
  title=str(candidate['fields'].get('文章标题','')) if candidate else ''
  quoted=' '.join(e['quote'] for e in rows)
  valid=current or bool(target and len(target)>=4 and (target in norm(title) or target in norm(quoted)) and (not city or city in title+' '+quoted))
  if valid:
   for e in rows:
    # A school/hospital commissioned beside a residential development is not
    # proof of the residential developer, even in the current article.
    external_agent=(field=='entity' and re.search(r'小学|中学|学校|医院',e['quote'])
                    and re.search(r'代建|承建',e['quote']) and target not in norm(e['quote']))
    # In a comparison source, a target mention elsewhere must not license
    # an unrelated project's standalone company paragraph as target proof.
    comparison_fragment=(not current and target not in norm(title)
                         and target not in norm(e['quote']))
    (discarded if external_agent or comparison_fragment else accepted).append(e)
  else:discarded.extend(rows)
 return accepted,discarded

def identity_note(values,proofs,project=''):
 # Free-text model reasoning is retained internally, not published as an
 # asserted same-project/alias relationship. Quote actual accepted evidence.
 chunks=[]
 for field,label in [('brand','品牌'),('entity','经营主体'),('city','城市')]:
  if not values[field]:
   chunks.append(label+'未取得充分原文依据，留空');continue
  es=[e for e in proofs[field] if values[field] in e['quote']]
  if not es:
   chunks.append(label+'按已核实经营主体归一为'+values[field]);continue
  # Prefer an explicit project-to-value relation over a shorter generic
  # brand paragraph, even when the latter comes from a same-title source.
  target=norm(project)
  e=min(es,key=lambda e:(not bool(target and target in norm(e['quote'])),not e['is_current_source'],len(e['quote'])))
  chunks.append(label+'='+values[field]+'；依据['+e['source_id']+'/'+e['field']+']：'+e['quote'])
 return '；'.join(chunks)

def process(result,business,runner):
 doc=result['document'];units=[u for u in result['semantic_partition'] if u['deliver']]
 candidates=evidence_candidates(doc,units,business);grid=evidence_grid(candidates);by_id={e['id']:e for e in grid}
 entity_brand={r['经营主体']:r['品牌组'] for r in business['rows'] if r.get('经营主体')}
 names={u.get('project') for u in units if u.get('project')}
 if len(names)==1:
  for u in units:
   if not u.get('project'):u['project']=next(iter(names))
 groups={}
 for u in units:groups.setdefault(u.get('project',''),[]).append(u)
 audit=[];role='身份不明';role_proofs=[]
 for project,group in groups.items():
  payload={'target_project':project,'source_id':doc['source_id'],'source_title':doc['row'].get('文章标题',''),'allowed_entities':entity_brand,'business_dictionary':business,'evidence_grid':grid}
  previous=None;error=None
  for attempt in range(2):
   answer=pipe.call(runner,doc,IDENTITY_GRID,payload if not attempt else {**payload,'previous':previous,'validation_error':error},'专题一身份原文证据编号核验' if not attempt else '专题一身份编号合同修复')
   try:
    values={};proofs={}
    for field in ['brand','entity','city','publisher_role']:
     x=answer.get(field);assert isinstance(x,dict) and isinstance(x.get('value'),str) and isinstance(x.get('evidence_ids'),list),'身份字段结构不完整'
     ids=x['evidence_ids'];assert all(type(i)==int and i in by_id for i in ids),'身份引文ID不合法'
     proofs[field]=[by_id[i] for i in sorted(set(ids))];values[field]=x['value']
    rejected=[];discarded_proofs={}
    for field in ['brand','entity','city']:
     proofs[field],discarded_proofs[field]=scoped_identity_proofs(project,values['city'],field,proofs[field],candidates,doc['source_id'])
    if values['entity'] and (values['entity'] not in entity_brand or not any(values['entity'] in e['quote'] for e in proofs['entity']) or values['brand']!=entity_brand.get(values['entity'])):
     rejected.append({'field':'entity','proposed':values['entity'],'reason':'经营主体非枚举、缺明示引文或与品牌不匹配；不将项目公司无据上推集团。'})
     values['entity']=''
    if values['entity']:
     # Exact company names alone do not establish same-project identity. Each
     # external source must itself tie the claimed entity to the target name;
     # another project of the same brand is not transferable corroboration.
     target=norm(project);valid_entity_sources=[]
     for source_id in {e['source_id'] for e in proofs['entity']}:
      evidence=[e for e in proofs['entity'] if e['source_id']==source_id]
      if source_id==str(doc['source_id']):valid_entity_sources.append(source_id);continue
      candidate=next(c for c in candidates if str(c['source_id'])==source_id)
      title=str(candidate['fields'].get('文章标题',''))
      quoted=' '.join(e['quote'] for e in evidence)
      anchored=bool(target and len(target)>=4 and (target in norm(quoted) or target in norm(title)))
      city_ok=not values['city'] or values['city'] in title+' '+quoted
      if anchored and city_ok:valid_entity_sources.append(source_id)
     if not valid_entity_sources:
      rejected.append({'field':'entity','proposed':values['entity'],'reason':'经营主体引文未同时核实目标案名及同城；不同楼盘、异地同名不互传。'})
      values['entity']=''
    for field in ['brand','city']:
     if values[field] and not (any(values[field] in e['quote'] for e in proofs[field]) or (field=='brand' and values['entity'])):
      if attempt==0:raise AssertionError('品牌/城市缺对应明确引文')
      rejected.append({'field':field,'proposed':values[field],'reason':'两次身份核验仍缺对应明确原文引文，保守留空，不凭板块名推城市或无据补品牌。'})
      values[field]=''
    assert values['publisher_role'] in pipe.ROLES,'发布者角色枚举不合法'
    break
   except (AssertionError,ValueError,KeyError,TypeError) as e:previous=answer;error=str(e)
  else:raise ValueError('身份核验合同修复失败：'+str(error))
  role=values['publisher_role'];role_proofs=[e for e in proofs['publisher_role'] if e['is_current_source'] and e['field']!='作者名字']
  if not role_proofs:role='身份不明'
  note=identity_note(values,proofs,project)
  if rejected:note+='；无据预测已驳回：'+ '；'.join(x['reason'] for x in rejected)
  for u in group:
   u.update({k:values[k] for k in ['brand','entity','city']})
   row=next(r for r in result['rows'] if r['起点']==u['start'] and r['终点']==u['end'])
   row.update({'品牌组':values['brand'],'经营主体':values['entity'],'城市':values['city'],'备注':(row.get('备注','')+'；'+note).strip('；')})
   audit.append({'index':u['index'],'values':values,'field_proofs':proofs,'discarded_proofs':discarded_proofs,'proofs':[e for ps in proofs.values() for e in ps],'errors':[],'rejected_predictions':rejected,'reason':note,'model_draft_reason':answer.get('same_project_reason','')})
 for row in result['rows']:row['发布者角色']=role
 result.update({'publisher_role':role,'identity_audit':audit,'identity_candidates':candidates,'publisher_identity_proofs':role_proofs,'identity_version':'identity-grid-v2'})
 return result
