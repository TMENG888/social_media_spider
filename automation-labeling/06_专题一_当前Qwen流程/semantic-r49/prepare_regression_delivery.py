"""Offline delivery adapter. Never imported by the model runner."""
import sys,json,copy,hashlib,importlib.util,statistics,re
from pathlib import Path
sys.dont_write_bytecode=True
sys.stdout.reconfigure(encoding='utf8')
R=Path(__file__).parent
def read(p):return json.loads(Path(p).read_text(encoding='utf8'))
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def excel_brand_evidence(value,sid):
 if len(value.encode('utf-16-le'))//2<=32767:return value,None
 entries=json.loads(value);before=sum(len(e['证据']) for e in entries)
 for entry in entries:
  names=[x for x in re.split('[;；、,，]',entry['品牌']) if x]
  local=[];seen=set()
  for proof in entry['证据']:
   marker=json.dumps(proof,ensure_ascii=False,sort_keys=True)
   if str(proof['key'])==str(sid) and any(b in proof['quote'] for b in names) and marker not in seen:
    local.append(proof);seen.add(marker)
  assert local and all(any(b in p['quote'] for p in local) for b in names),'超长品牌证据缺少本来源明示品牌依据'
  entry['证据']=local
  entry['理由']='本来源明示品牌；交付保留本来源的完整原文引文，全部身份核验记录内部保留。不移植其他来源产品配置。'
 result=json.dumps(entries,ensure_ascii=False,separators=(',',':'))
 assert len(result.encode('utf-16-le'))//2<=32767,'本来源品牌证据仍超过Excel单格上限，需另行处理，禁止截断'
 return result,{'source_id':sid,'original_evidence_count':before,'retained_evidence_count':sum(len(e['证据']) for e in entries),'original_sha256':hashlib.sha256(value.encode('utf8')).hexdigest(),'quotes_truncated':False}
def module(name,p):
 s=importlib.util.spec_from_file_location(name,p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
def prepare(batch,version,source_path=None,input_path=None,dest_dir=None,empty_review_path=None,diagnostic=False,heat_baseline_files=None):
 if batch=='C' and not (R/'frozen_version.json').exists():raise RuntimeError('C not yet frozen')
 source=Path(source_path) if source_path else R/f'run_{version}'/f'{batch}_results.json';raw=read(source)
 input_file=Path(input_path) if input_path else R/'inputs'/f'{batch}_documents.json'
 assert len(raw)==len(read(input_file)) and all(r['complete'] for r in raw)
 base=module('t1_delivery_aggregator','E:/Codex/work/20261021_专题一参考集A_交付结构修订/prepare_delivery.py')
 heat=module('heat_resolver','C:/Users/YS-Insight/Desktop/陈晓锋/自动化打标/04_专题二_观点信息单元/topic2_heat_v110.py')
 schemas=read('E:/Codex/work/20261021_专题一参考集A_交付结构修订/schema.json')
 target={s['name']:s['headers'] for s in read('E:/Codex/work/20261021_专题一移除项目字段/Codex_plan.json')['sheets']}
 taxonomy={t['tag_id']:t for t in read(R/'inputs/taxonomy.json')}
 resolver=heat.HeatResolver(files=heat_baseline_files);normalized=[];metrics={}
 for result in raw:
  d=copy.deepcopy(result['document']);d['row']['发布者角色']=result['publisher_role'];sid=d['source_id']
  comparison_row=d['row']
  if heat_baseline_files and heat.existing_heat(d['row'].get('热度指数')) is None:
   resolver.load()
   if sid not in resolver.parents:raise ValueError('新全量热度快照缺少来源：'+sid)
   snapshot_row=resolver.parents[sid];comparison_row=copy.deepcopy(d['row']);normalized_fields=[]
   for field in ('平台','内容类型','项目',*heat.FIELDS):
    if field not in comparison_row:continue
    value=comparison_row[field];baseline=snapshot_row.get(field)
    if value==baseline:continue
    # SQL/JSON numbers and CSV strings may represent the identical input.
    # Check semantic equality first; never hide changed source interactions.
    equal=(heat.count_value(value)==heat.count_value(baseline)) if field in heat.FIELDS else (('' if value is None else str(value))==('' if baseline is None else str(baseline)))
    if not equal:raise ValueError(f'原始互动值已变化，不能混用热度快照：{sid}/{field}')
    comparison_row[field]=baseline;normalized_fields.append(field)
   if normalized_fields:resolver.audit.setdefault('input_representation_normalizations',[]).append({'source_id':sid,'fields':normalized_fields,'raw_input_changed':False})
  h=resolver.resolve(sid,d['row'].get('热度指数'),parent_row=comparison_row)
  metrics[sid]={'heat':h,'depth':None,'note':'' if heat.existing_heat(d['row'].get('热度指数')) is not None else ('热度按两专题全量同平台及内容类型基准补算。' if h is not None else '热度缺失：同组有效互动数据不足，未补零。')}
  units=[]
  for row,u in zip(result['rows'],[p for p in result['semantic_partition'] if p['deliver']]):
   assert row['起点']==u['start'] and row['终点']==u['end']
   units.append({**row,'start':u['start'],'end':u['end'],'标签ID':[p['tag_id'] for p in u['labels']],'proofs':u['labels']})
  normalized.append({'document':d,'units':units})
 base.sha=lambda p:sha(input_file) if Path(p).name=='documents.json' else sha(source)
 # Local sub-slices may repeat a quote appearing earlier in the full article.
 # Export against the validated frozen offsets, not the local occurrence number.
 build_raw=copy.deepcopy({r['document']['source_id']:r for r in raw})
 anchor_repairs=[]
 for sid,r in build_raw.items():
  text=r['document']['text'];pos=0
  pu=r['full_source_partition']['units'];sp=r['semantic_partition']
  assert len(pu)==len(sp)
  for p,u in zip(pu,sp):
   assert u['start']==pos and u['end']>pos and text[pos:u['end']]==u['text']
   assert (p['start'],p['end'])==(u['start'],u['end'])
   # Identity repair updates semantic_partition and rows. A separately
   # serialized full_source_partition can retain pre-repair brands; export
   # denominators must follow the final confirmed identity, not that draft.
   p['brand']=u.get('brand')
   if 'metadata_identity_audit' in u:p['metadata_identity_audit']=copy.deepcopy(u['metadata_identity_audit'])
   else:p.pop('metadata_identity_audit',None)
   quote=p['start_quote'];assert quote and text.startswith(quote,pos)
   occurrence=0;found=-1
   while found<pos:
    found=text.find(quote,found+1);assert found>=0
    occurrence+=1
   assert found==pos
   if occurrence!=int(p.get('start_occurrence') or 1):
    anchor_repairs.append({'source_id':sid,'start':pos,'old_occurrence':p.get('start_occurrence'),'global_occurrence':occurrence})
    p['start_occurrence']=occurrence
   pos=u['end']
  assert pos==len(text)
 plan=base.build('Qwen',normalized,build_raw,schemas,taxonomy,metrics)
 plan['export_anchor_normalizations']=anchor_repairs
 by_source={r['document']['source_id']:r for r in raw}
 prohibited={'项目','验收状态','互动深度指数','涉及文章数','参与文章数','命中切片数','组内全部切片数','有热度文章数','缺热度文章数','字典ID'}
 evidence_compactions=[]
 for sheet in plan['sheets']:
  name=sheet['name'];old=sheet['headers'];new=target[name]
  sheet['rows']=[[row[old.index(h)] if h in old and old.index(h)<len(row) else None for h in new] for row in sheet['rows']]
  sheet['headers']=new
  assert not prohibited.intersection(new)
  if name=='议题指标' or name.endswith('_议题指标'):
   sheet['top']=['品牌分组','全部' if name=='议题指标' else name.split('_')[0]]
   sheet['notes']=[['覆盖率','去重命中文章数÷组内全部参与文章数。'],['浓度','去重命中切片数÷组内完整语义分区数，含内部无标签片。'],['热度','命中文章去重后，取有效文章热度中位数。'],['缺值','无命中热度留空；无分母时比率留空。'],['热度补算','有效原值保留；仅缺值按两专题全量同平台、内容类型基准补算。'],['字典范围','专题一全部323条适用标签，含零命中。'],['来源角色','有原文身份证据才判断；无证据为身份不明。']]
  if name=='产品信息单元':
   ix={h:i for i,h in enumerate(new)}
   assert len(new)==35
   for row in sheet['rows']:
    r=by_source[row[ix['源表id']]]
    a=next(a for a in r['identity_audit'] if any(u['index']==a['index'] and u['start']==row[ix['起点']] for u in r['semantic_partition']))
    brand=row[ix['品牌组']]
    row[ix['品牌分类依据']]=json.dumps([{'品牌':brand,'理由':'同一目标住宅原文身份核实；不使用其他楼盘的配置。','证据':[{'key':e['source_id'],'field':e['field'],'quote':e['quote'],'url':e.get('url')} for e in a['field_proofs']['brand']]}] if brand else [],ensure_ascii=False,separators=(',',':'))
    row[ix['品牌分类依据']],compaction=excel_brand_evidence(row[ix['品牌分类依据']],row[ix['源表id']])
    if compaction:evidence_compactions.append({'unit_id':row[ix['unit_id']],**compaction})
    row[ix['明细口径']]='专题一产品信息单元'
    row[ix['说明']]='摘录保留原文，标签证据见打标说明；无历史记录的历史字段留空。'
    row[ix['热度来源']]='保留原值' if heat.existing_heat(r['document']['row'].get('热度指数')) is not None else ('两专题全量同平台＋内容类型补算' if metrics[row[ix['源表id']]]['heat'] is not None else '缺少同组有效互动数据，未补零')
 # Independent all-brand metric check against final source/partition truth.
 allsheet=next(s for s in plan['sheets'] if s['name']=='议题指标')
 part_count=sum(len(r['semantic_partition']) for r in raw)
 for v in allsheet['rows']:
  path=tuple(v[:5]);t=next(t for t in taxonomy.values() if tuple([t['l1'],t['l2'],t['l3'],t['l4'] or '不设四级（原字典）',t['l5'] or '不设五级（原字典）'])==path)
  hits=[(r['document']['source_id'],u) for r in raw for u in r['semantic_partition'] if any(p['tag_id']==t['tag_id'] for p in u['labels'])]
  sids={s for s,u in hits};heats=[metrics[s]['heat'] for s in sids if metrics[s]['heat'] is not None]
  assert v[6]==len(sids)/len(raw) and v[7]==len(hits)/part_count
  assert v[8]==(statistics.median(heats) if heats else None)
 plan.update(batch=batch,model='Qwen',version=version,annotation_sha256=sha(source),input_sha256=sha(input_file),export_evidence_compactions=evidence_compactions)
 if source_path:plan['delivery_kind']='批量'
 dest=(Path(dest_dir) if dest_dir else R/f'run_{version}')/f'{batch}_delivery_plan.json'
 # Final export hides all empty-label rows; frozen misses/partitions stay internal.
 review_path=Path(empty_review_path) if empty_review_path else dest.parent/f'{batch}_empty_label_review.json'
 review={'reviews':{}}
 if empty_review_path and not review_path.exists():raise ValueError('指定的复核记录不存在')
 if review_path.exists():
  review=read(review_path)
  if review['input_sha256']!=sha(source):raise ValueError('空标签复核记录与本轮标注哈希不符')
 delivery_filter=module('topic1_reviewed_delivery_filter','C:/Users/YS-Insight/.codex/skills/voc-topic1-labeling/scripts/delivery_filter.py')
 plan=delivery_filter.filter_plan(plan,review['reviews'],final=not diagnostic)
 if review_path.exists():plan['empty_label_review_sha256']=sha(review_path)
 dest.parent.mkdir(parents=True,exist_ok=True)
 dest.write_text(json.dumps(plan,ensure_ascii=False,indent=2,default=lambda x:sorted(x) if isinstance(x,set) else str(x)),encoding='utf8')
 (dest.parent/f'{batch}_delivery_metrics.json').write_text(json.dumps({'sources':metrics,'heat_audit':resolver.audit},ensure_ascii=False,indent=2),encoding='utf8')
 print(json.dumps({'batch':batch,'source_count':len(raw),'units':plan['unit_count'],'partition_count':part_count,'plan':str(dest)},ensure_ascii=False))
if __name__=='__main__':prepare(sys.argv[1],sys.argv[2])
