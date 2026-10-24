"""Two workbook payloads for fresh 500-per-topic runs, not historical samples."""
import argparse,json,copy
from pathlib import Path
from collections import defaultdict,Counter
import delivery_v4 as b
from delivery_label_reference_v91 import reference_tables,enrich_rows,display_schema,REFERENCE_FIELDS
from package_two_workbooks_v87 import statistics,content_type,supplement_costs
from project_context_v90 import project_ids
from token_cost_report_v93 import report

def package(directory,taxonomy_path):
 data=json.loads((directory/'delivery_results.json').read_text(encoding='utf-8'))
 refs,ref_source=reference_tables(taxonomy_path);tax=b.load_taxonomy(taxonomy_path)
 registry={t['tag_id']:b.label_json(t) for t in tax}
 docs=data['results'];counts=Counter(r['document']['topic'] for r in docs if r['document']['kind']=='文章')
 assert counts=={b.T1:500,b.T2:500} and sum(r['document']['kind']=='评论' for r in docs)==956
 assert [r['document']['record_id'] for r in docs]==data['execution_manifest']['requested_record_ids']
 cost=report(directory);cost_phase=supplement_costs(directory)
 # The initial real-API policy probe is billed too; it is not one of the source
 # articles, and must not disappear from this turn's cost accounting.
 if (directory/'smoke'/'calls').exists():
  probe=report(directory/'smoke')
  for key,value in probe['total'].items():cost['total'][key]+=value
  cost['by_topic_source']+=probe['by_topic_source']
  for topic,items in supplement_costs(directory/'smoke').items():cost_phase.setdefault(topic,[]).extend(items)
 cost['scope']='本轮主体程序加启动口径API测试；含全部保存的失败重试，不含历史目录，不重复计缓存读取。'
 b.save_json(directory/'token_cost_summary_all_stages.json',cost)
 payloads=[];verified=[];used_ids=set()
 for topic,name in [(b.T1,'产品信息单元'),(b.T2,'观点信息单元')]:
  results=[r for r in docs if r['document']['topic']==topic];main=[];sources=[];pending=[];excluded=[];audit=[];proofs=[];coverage=[];humans=[]
  project_sources=defaultdict(set);project_units=Counter()
  for result in results:
   doc=result['document'];assert len(result['rows'])==len(result['traces'])
   delivered=[]
   for row,trace in zip(result['rows'],result['traces']):
    assert row['unit_id'] not in used_ids;used_ids.add(row['unit_id'])
    quote=row.get('原文摘录',row.get('原始摘录'));assert quote==doc['text'][trace['起点']:trace['终点']]
    ids=[t['标签路径ID'] for t in row['标签明细']];assert len(ids)==len(set(ids))
    assert all(t==registry[t['标签路径ID']] for t in row['标签明细'])
    if doc['kind']=='评论':
     assert len(result['rows'])==1 and quote==doc['text'] and row['映射文章id']==doc['row']['文章id']
    assert all(row[h]==b.numeric_score(doc['parent'].get(h)) for h in ['热度指数','互动深度指数'])
    prose=row.get('具体产品做法',row.get('观点摘要'))
    missing=[h for h,v in [('标签明细',row['标签明细']),('打标说明',row.get('打标说明')),('做法/摘要',prose)] if not v]
    if missing:
     pending.append({'unit_id':row['unit_id'],'record_id':doc['record_id'],'来源类型':doc['kind'],'原文':quote,
       '起点':trace['起点'],'终点':trace['终点'],'未完成原因':'字段修复仍未确认：'+','.join(missing),'已确认标签明细':row['标签明细'],'已有打标说明':row.get('打标说明'),
       '已有做法或摘要':prose,'人工审核结果':'待审核'})
    else:delivered.append(row)
    proofs.append({'unit_id':row['unit_id'],'record_id':doc['record_id'],'来源类型':doc['kind'],
      '起点':trace['起点'],'终点':trace['终点'],'原文证据':quote,'标签证据与归属':trace.get('标签证据与归属'),
      '模型补标证据':trace.get('全字典补选证据'),'关键词补标证据':trace.get('关键词补标证据'),
      '联合关键词补标证据':trace.get('联合关键词补标证据'),'项目上下文修复':trace.get('项目上下文修复'),
      '全文归属补全与未补原因':trace.get('归属补全-v97')})
   enriched=enrich_rows(delivered,refs[topic]);main+=enriched
   for row in enriched:
    pname=(row.get('项目') or '未确定项目') if topic==b.T1 else ';'.join(row.get('项目名称') or []) or '非研究项目/项目待核'
    pkey=(pname,doc['row'].get('平台'),doc['kind'])
    project_sources[pkey].add(doc['record_id']);project_units[pkey]+=1
    humans.append({'unit_id':row['unit_id'],'record_id':doc['record_id'],'来源类型':doc['kind'],'原文':row.get('原文摘录',row.get('原始摘录')),
     '待审原因':row['备注'],'当前标签明细':row['标签明细'],'人工审核结果':'待审核','修改后标签明细':'',
     '修改后摘要或做法':'','复核人':'','复核时间':''})
   sources.append({'record_id':doc['record_id'],'源表id':doc['source_id'],'来源类型':doc['kind'],'父文章ODS主键':str(doc['parent']['id']),
     '评论平台文章id':doc['row'].get('文章id') if doc['kind']=='评论' else None,'平台':doc['row'].get('平台'),'内容类型':content_type(doc),
     '主体字段':doc['field'],'主体字数':len(doc['text']),'文章标题':doc.get('title'),'原始主体':doc['text'],
     '热度指数':b.numeric_score(doc['parent'].get('热度指数')),'互动深度指数':b.numeric_score(doc['parent'].get('互动深度指数')),
     '处理状态':'已完成' if result['complete'] else '待核事项未全部解决','交付单元数':len(delivered),
     '全字典遍历完成':result['label_supplement_coverage']['all_branches_checked'],'关联后不强推项目':True})
   for p in result.get('pending_units',[]):
    pending.append({'unit_id':p['unit_id'],'record_id':doc['record_id'],'来源类型':doc['kind'],'原文':p['原文'],
      '起点':p['起点'],'终点':p['终点'],'未完成原因':p['原因'],'已确认标签明细':(p.get('旧单元') or {}).get('标签明细'),
      '人工审核结果':'待审核'})
   for e in result.get('excluded_intervals',[]):
    excluded.append({'record_id':doc['record_id'],'来源类型':doc['kind'],'平台':doc['row'].get('平台'),'原单元ID':e.get('原单元ID'),
      '原文':e['原文'],'排除原因':e['原因']})
   for e in result.get('label_supplement_events',[]):
    audit.append({'record_id':doc['record_id'],'unit_id':e.get('unit_id'),'标签路径ID':'VOC-'+e['key'][1:] if e.get('key') else None,
      '处理':e['处理'],'原因':e.get('原因',e.get('reason')),'属性证据':e.get('quotes'),'对象证据':e.get('context_quotes'),
      '置信度':e.get('confidence'),'补标方法':e.get('decision_method'),'规则版本':e.get('rule_version')})
   c=result['label_supplement_coverage']
   coverage.append({'record_id':doc['record_id'],'来源类型':doc['kind'],'平台':doc['row'].get('平台'),
     '适用字典标签数':c['applicable_dictionary_count'],'单片标签分组数':c['branch_count'],'扫描请求数':c['scan_request_count'],
     '每请求目标单元数':1,'字典遍历完成':c['all_branches_checked'],'全部候选审理完成':c['all_candidates_adjudicated'],
     '待核候选数':len(result['label_supplement_deferred']),'未解决事实数':len(c['remaining_facts']),'API或合同异常':c['errors']})
  # Statistics recomputed from the actual delivered rows, while source denominator
  # remains all 500 articles plus all real comments (never accepted-units only).
  stats_results=copy.deepcopy(results);by_source=Counter(r['record_id'] for r in main)
  for r in stats_results:r['rows']=[x for x in main if x['record_id']==r['document']['record_id']]
  stats=statistics(stats_results)
  summary={'文章入场数':500,'评论入场数':sum(r['document']['kind']=='评论' for r in results),
    '交付单元数':len(main),'文章信息单元数':sum(r.get('来源类型','文章')=='文章' for r in main),
    '评论信息单元数':sum(r.get('来源类型')=='评论' for r in main),'待核单元数':len(pending),
    '全字典遍历完成来源数':sum(r['label_supplement_coverage']['all_branches_checked'] for r in results)}
  table_cost=cost_phase.get(topic,[])
  payload={'filename':name+'_500篇文章批量交付.xlsx','main_name':name,'topic':topic,'summary':summary,
    'schemas':{name:display_schema(b.PRODUCT_FIELDS if topic==b.T1 else b.VIEW_FIELDS),
      '专题一标签体系' if topic==b.T1 else '专题二标签体系':REFERENCE_FIELDS},
    'tables':{name:main,('专题一标签体系' if topic==b.T1 else '专题二标签体系'):refs[topic],
      '测试渠道统计':stats,'项目平台文章评论统计':[{'项目名称':key[0],'平台':key[1],'来源类型':key[2],
        '有交付单元来源数':len(value),'交付单元数':project_units[key]} for key,value in sorted(project_sources.items())],
      '源记录与文章关联':sources,'抽样与平台缺口':[c for c in data['sampling']['coverage'] if c['专题']==topic],
      '补选覆盖记录':coverage,'标签补选与纠错':audit,'原文标签证据':proofs,'未完成待核':pending,'排除区间':excluded,
      '人工审核':humans,'本轮Token费用':table_cost,
      **({'评论关联待核':data['sampling']['comment_mapping_issues']} if topic==b.T2 else {})},
    'reference_source':ref_source,'notes':['本轮全新批量运行：专题一500篇、专题二500篇；956条真实评论在文章名额之外追加。',
      '专题一四平台各125篇；专题二小红书250篇、公众号192篇、网页58篇，视频号无可用主体。',
      '种子20261008；渠道内长度分层；专题二优先全部226篇有可用正文且可唯一关联评论的文章。',
      '文章主体按正文、视频文本、已有OCR首个非空选择，不拼接；文章语义切片，评论完整一行。',
      '每片单独遍历完整适用字典分组；真实字典回填标签八键，同片按ID去重。',
      'VOC-0377新口径：明确会所内有健身房即可标，无需具体器械明细；外部健身房、泛谈不适用。',
      '来源总数与交付单元数分别统计；无关内容保留排除记录，未确认内容保留待核，不冒充全量准确率。',
      '项目统计按组合名称与平台、文章/评论分开；同篇不同项目可分别计入，跨项目合计不可当去重文章总数。',
      '评论平台文章id保留CSV原值，父文章ODS主键单独追溯；关联父文不自动等于评论项目归属。',
      '所有主表仍需人工审核；未知项目、源指数缺失不造值；Token为本轮所有实发尝试，缓存重读不重复计。',
      '非缓存输入0.20、缓存输入0.04、输出0.80元/百万Token；输入>32000价格未知，估算不是账单。']}
  b.save_json(directory/(name+'_workbook_payload.json'),payload);payloads.append(payload['filename']);verified.append(summary)
 b.save_json(directory/'bulk_final_contract.json',{'passed':True,'source_articles_per_topic':500,'real_comments':956,
    'all_sources_present':True,'dictionary_exact':True,'literal_source_positions':True,'complete_comments':True,'workbooks':verified,'cost':cost})
 print(b.dumps({'payloads':payloads,'summaries':verified,'cost':cost['total']}))

if __name__=='__main__':
 ap=argparse.ArgumentParser();ap.add_argument('--output-dir',type=Path,required=True);ap.add_argument('--taxonomy',type=Path,required=True);a=ap.parse_args()
 package(a.output_dir,a.taxonomy)
