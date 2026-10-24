"""T2 export payload from completed unit sentiment, never from CSV sentiment."""
import statistics
from collections import Counter,defaultdict
import slice_sentiment_v107 as default_sentiment
from topic2_heat_v110 import HeatResolver,existing_heat

FIELDS=['一级标签','二级标签','三级标签','四级标签','五级标签','标签名']

def aggregate(records,taxonomy,projects,parent_heats=None,ad_decisions=None,*,sentiment_engine=None,heat_baseline_files=None):
 sentiment=sentiment_engine or default_sentiment
 # The same established grounded-label/evidence serializer, not a new tagger.
 import topic2_pipeline_v106 as entry
 p=entry.legacy.q.p
 from voc_four_evidence_packing_v101 import pack
 tax={t['tag_id']:t for t in taxonomy};pm={x['id']:x for x in projects}
 if len(tax)!=len(taxonomy):raise ValueError('Duplicate taxonomy IDs')
 sources=[];units=[];pairs={};parents={};seen=set();heat_resolver=HeatResolver(heat_baseline_files)
 for record in records:
  rid=record['record_id'];doc=record['document']
  if rid in seen or record['state']!='accepted' or record.get('unfinished_units'):raise ValueError('Duplicate/unfinished source')
  seen.add(rid)
  if set(record['outcomes'])!={u['unit_id'] for u in record['units']}:raise ValueError('Outcome coverage mismatch')
  cursor=0
  for u in record['units']:
   if u['start']!=cursor or doc['text'][u['start']:u['end']]!=u['text']:raise ValueError('Partition gap/overlap')
   cursor=u['end'];sentiment.unit_result(record,u['unit_id'])
  if cursor!=len(doc['text']):raise ValueError('Unprocessed source tail')
  parent=str(doc['parent']['id']);row=doc['row']
  date=row.get('评论时间' if doc['kind']=='评论' else '文章时间地点')
  if not date or not row.get('平台') or not record.get('publisher',{}).get('role'):raise ValueError('Required source metadata absent')
  # Existing values (including zero) are never replaced by a recalculated rank.
  supplied=existing_heat(parent_heats.get(parent)) if parent_heats is not None else None
  original=existing_heat(doc['parent'].get('热度指数'))
  if supplied is not None and original is not None and supplied!=original:
   raise ValueError('Explicit heat map conflicts with existing parent heat')
  heat=heat_resolver.resolve(parent,supplied if supplied is not None else original,parent_row=doc['parent'])
  parents[parent]={'parent_id':parent,'title':doc['parent'].get('文章标题') or '',
   'platform':doc['parent'].get('平台') or row['平台'],'heat':heat,
   'url':doc['parent'].get('文章链接') or '', 'platform_article_id':str(doc['parent'].get('文章id') or '')}
  catalog=p.v.supplement.evidence_catalog(record['units']);projects_hit=set()
  for item in record['units']:
   value=sentiment.unit_result(record,item['unit_id']);score=value['score']
   for view in record['outcomes'][item['unit_id']]['views']:
    pid=view['project_id'];labels=view['labels']
    if pid not in pm or not labels or len({l['tag_id'] for l in labels})!=len(labels):raise ValueError('Invalid project/tag view')
    projects_hit.add(pid)
    evidence=pack(view,catalog)
    if isinstance(evidence,str):
     import json
     evidence=json.loads(evidence)
    evidence={**evidence,'slice_sentiment':value,'sentiment_version':sentiment.VERSION}
    units.append({'切片ID':item['unit_id']+'@'+pid,'原切片ID':item['unit_id'],'record_id':rid,'来源类型':doc['kind'],
     '源表id':doc['source_id'],'父文章ODS主键':parent,'project_id':pid,'项目名称':pm[pid]['name'],'项目角色':pm[pid]['role'],
     '发布日期':date,'平台':row['平台'],'发布者角色':record['publisher']['role'],'起点':item['start'],'终点':item['end'],
     '原始摘录':item['text'],'观点摘要':view['summary'],'标签明细':[p.v.b.label_json(tax[l['tag_id']]) for l in labels],
     '打标说明':'；'.join(l['tag_id']+'｜对象='+l['object']+'｜'+l['reason'] for l in labels),
     '表达类型':';'.join(dict.fromkeys(view['expressions'])),'情绪态度':';'.join(dict.fromkeys(view['emotions'])),
     '情绪评分':score,'热度指数':heat,'处理方式':'保留切片和标签；切片完成后本地RoBERTa独立评分',
     '审核口径':'情绪只读当前切片；原分留档；非人工金标准','项目与标签证据':evidence})
    for label in labels:
     for group in ('全部',pid):
      pair=pairs.setdefault((group,label['tag_id'],rid),{'group':group,'tag_id':label['tag_id'],'record_id':rid,
       'kind':doc['kind'],'parent_id':parent,'unit_ids':set(),'project_ids':set()})
      pair['unit_ids'].add(item['unit_id']);pair['project_ids'].add(pid)
  if not projects_hit:raise ValueError('No valid four-project labels in selected source')
  decision=(ad_decisions or {}).get(doc['source_id'],{})
  own_ad=row.get('是否广告') if doc['kind']=='文章' else decision.get('is_ad')
  if own_ad!='否':raise ValueError('Non-admission not confirmed for source')
  source_score=statistics.mean(sentiment.unit_result(record,u['unit_id'])['score'] for u in record['units'])
  sources.append({'record_id':rid,'kind':doc['kind'],'source_id':doc['source_id'],'parent_id':parent,
   'platform':row['平台'],'own_date':date,'publisher':record['publisher']['role'],'publisher_reason':record['publisher']['reason'],
   'score':source_score,'score_legacy':record.get('score'),'score_method':sentiment.VERSION,
   'title':doc.get('title') or '','text':doc['text'],'parent_title':parents[parent]['title'],
   'platform_article_id':parents[parent]['platform_article_id'],'platform_comment_id':str(row.get('评论id') or ''),
   'url':row.get('文章链接') or parents[parent]['url'],'field':doc['field'],'semantic_slices':len(record['units']),
   'projects':sorted(projects_hit),'heat':heat,'own_ad':own_ad,'own_ad_reason':decision.get('reason') or '源CSV明确标记否',
   'parent_ad_flag':doc['parent'].get('是否广告') or '', 'catalogue_checked':True,'prior_selected_reuse':True})
 by={r['record_id']:r for r in records};grouped=defaultdict(list)
 for pair in pairs.values():
  pair['unit_ids']=sorted(pair['unit_ids']);pair['project_ids']=sorted(pair['project_ids'])
  pair['score']=statistics.mean(sentiment.unit_result(by[pair['record_id']],uid)['score'] for uid in pair['unit_ids'])
  grouped[pair['group'],pair['tag_id']].append(pair)
 groups=['全部',*[p['id'] for p in projects]];pair_rows=[];heat_rows=[];metrics=[]
 for group in groups:
  denominator=len(sources) if group=='全部' else sum(group in x['projects'] for x in sources)
  for tag in taxonomy:
   entries=sorted(grouped[group,tag['tag_id']],key=lambda x:x['record_id']);first_pair=len(pair_rows)+6;pair_rows.extend(entries)
   ids=sorted({x['parent_id'] for x in entries});first_heat=len(heat_rows)+6
   heat_rows.extend({'group':group,'tag_id':tag['tag_id'],**parents[k]} for k in ids)
   hs=[parents[k]['heat'] for k in ids if parents[k]['heat'] is not None]
   metrics.append({'group':group,'tag_id':tag['tag_id'],**{FIELDS[i-1]:tag.get('l'+str(i)) or '' for i in range(1,6)},'标签名':tag['emphasis'],
    'denominator':denominator,'data_count':len(entries),'ratio':len(entries)/denominator if denominator else None,
    'sentiment':statistics.mean(x['score'] for x in entries) if entries else None,
    'heat':statistics.median(hs) if hs else None,'heatN':len(hs),'missingHeat':len(ids)-len(hs),
    'article_count':sum(x['kind']=='文章' for x in entries),'comment_count':sum(x['kind']=='评论' for x in entries),
    'first_pair':first_pair,'last_pair':len(pair_rows)+5,'first_heat':first_heat,'last_heat':len(heat_rows)+5})
 metrics.sort(key=lambda x:(groups.index(x['group']),-x['data_count'],x['tag_id']))
 channels=[]
 for platform in sorted({s['platform'] for s in sources}):
  for kind in ('文章','评论'):
   ss=[s for s in sources if s['platform']==platform and s['kind']==kind]
   channels.append({'platform':platform,'kind':kind,'sources':len(ss),'valid_score':len(ss),'heat_sources':sum(s['heat'] is not None for s in ss),
    'slice_views':sum(u['平台']==platform and u['来源类型']==kind for u in units)})
 return {'version':'topic2-v107','sentiment_version':sentiment.VERSION,'heat_baseline_files':[str(p) for p in heat_resolver.files],'heat_backfill_audit':heat_resolver.audit,'sources':sources,'units':units,'pairs':pair_rows,
  'heat_rows':heat_rows,'metrics':metrics,'taxonomy':taxonomy,'projects':projects,'channels':channels,
  'source_counts':dict(Counter(s['kind'] for s in sources)),'total_sources':len(sources),'total_slice_views':len(units),
  'original_slice_count':len({u['原切片ID'] for u in units}), 'metric_output_headers':FIELDS+['占比（%）','议题热度','情绪评分','数据量']}
