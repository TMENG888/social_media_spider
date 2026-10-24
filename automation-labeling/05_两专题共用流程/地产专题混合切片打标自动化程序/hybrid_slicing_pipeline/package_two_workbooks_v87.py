"""Prepare typed, traceable two-workbook payloads and source-grain statistics."""
import argparse,copy,json,re
from pathlib import Path
from collections import defaultdict
import delivery_v87 as pipeline
from delivery_label_reference_v91 import reference_tables, enrich_rows, display_schema, REFERENCE_FIELDS
from delivery_v4 import cached_tokens
from multilabel_v2 import calculate_cost

base=pipeline.base

def project_audit(result):
    return [{'unit_id':c['unit_id'],'处理':c['处理'],'项目ID':c['新项目ID'],
        '理由':(c.get('判断') or {}).get('why'),'校验问题':c['校验问题'],
        '依据':[{'来源':b['context_source'],'案名引文':b['identity_quote'],
            '身份起点':b['identity_start'],'身份终点':b['identity_end'],
            '单元起点':b['relation_start'],'置信度':b['confidence']} for b in c.get('定位证据',[])]}
        for c in result.get('project_context_changes',[])]

def has_value(v):return str(v or '').strip().lower() not in {'','[]','null','none','nan','0'}


def pending_fact_display(fact,result):
    """Audit display only: never present invented/translated quotes as evidence."""
    from full_dictionary_supplement_v92 import audit_units,evidence_catalog
    unit=next(u for u in audit_units(result) if u['unit_id']==fact['unit_id'])
    catalog={e['source_key']:e for e in evidence_catalog(audit_units(result))}
    literal=[];invalid=False
    for quote in fact.get('quotes',[]):
        if quote in catalog:
            entry=catalog[quote]
            if entry['unit_id']==unit['unit_id']:quote=entry['text']
        if quote.startswith('text:') and quote[5:] in unit['text']:quote=quote[5:]
        if quote and quote in unit['text']:literal.append(quote)
        else:invalid=True
    reason=fact['reason']
    if len(reason)>240:
        reason='模型未给出简洁且稳定的最终裁决，需按原文和真实标签定义人工复核；原始返回保留在运行审计中。'
    if invalid:reason='模型审核线索含未逐字定位的引文，不能当支持证据；'+reason
    return {'原文证据':list(dict.fromkeys(literal)) or '未取得可定位引文，请核对对应单元原文','待核原因':reason}


def supplement_costs(directory):
    """Actual cache records for this output run, including smoke/failed attempts."""
    buckets=defaultdict(list)
    for folder in ['calls','call_attempt_history']:
        for path in (directory/folder).glob('*.json'):
            metrics=json.loads(path.read_text(encoding='utf-8'))['metrics']
            buckets[(metrics['topic'],metrics['source_type'],metrics['phase'])].append(metrics)
    costs=defaultdict(list)
    for (topic,kind,phase),records in sorted(buckets.items()):
        attempts=[attempt for record in records for attempt in record['attempts']]
        usages=[attempt['usage'] for attempt in attempts if attempt.get('usage')]
        prices=[calculate_cost(u.get('prompt_tokens'),cached_tokens(u),u.get('completion_tokens')) for u in usages]
        costs[topic].append({'来源类型':kind,'阶段':phase,'实际请求记录数':len(records),
            'HTTP尝试数':len(attempts),
            '成功请求数':sum(c['status']=='success' for c in records),
            '已知输入Token':sum(u.get('prompt_tokens') or 0 for u in usages),
            '已知缓存Token':sum(min(u.get('prompt_tokens') or 0,cached_tokens(u)) for u in usages),
            '已知输出Token':sum(u.get('completion_tokens') or 0 for u in usages),
            '已知估算费用元':sum(price for price in prices if price is not None),
            '未知usage或价格请求数':sum(any(not attempt.get('usage') or calculate_cost(
                attempt['usage'].get('prompt_tokens'),cached_tokens(attempt['usage']),
                attempt['usage'].get('completion_tokens')) is None for attempt in record['attempts']) for record in records),
            '未知usage的HTTP尝试数':sum(not attempt.get('usage') for attempt in attempts),
            '口径':'本轮目录实发请求，含冒烟及失败重试；缓存重读不重复计费，非账单结算'})
    return dict(costs)

def content_type(doc):
    if doc['kind']=='评论':return '文本评论'
    row=doc['row'];kind=row.get('内容类型') or '未注明'
    # Preserve the source classification. Only already-labelled image/text
    # posts with a video link are separated; video cover images aren't retyped.
    if kind=='图文' and has_value(row.get('文章视频链接')):return '图文且视频'
    return kind

def statistics(results):
    buckets=defaultdict(list)
    for r in results:
        d=r['document'];buckets[(d['topic'],d['row'].get('平台'),d['kind'],content_type(d))].append(r)
    rows=[]
    for (topic,platform,kind,ctype),rs in sorted(buckets.items()):
        rows.append({'项目':topic,'平台':platform,'来源类型':kind,'内容类型':ctype,'范围内行数':len(rs),
            '热度可计算数':sum(base.numeric_score(r['document']['parent'].get('热度指数')) is not None for r in rs),
            '互动可计算数':sum(base.numeric_score(r['document']['parent'].get('互动深度指数')) is not None for r in rs),
            '有交付单元来源数':sum(bool(r['rows']) for r in rs),'交付单元数':sum(len(r['rows']) for r in rs),
            '未完成来源数':sum(not r['complete'] for r in rs),'排除区间数':sum(len(r.get('excluded_intervals',[])) for r in rs)})
    return rows

def evaluate(old,new):
    previous={r['document']['record_id']:r for r in old['results']};current={r['document']['record_id']:r for r in new['results']}
    def tags(rs,rid):return {t['标签路径ID'] for u in rs[rid]['rows'] for t in u['标签明细']} if rid in rs else set()
    anchors=[('保利建筑面积保留','T1-8000912876517501943','VOC-0186',True),
        ('保利赠送面积不硬凑','T1-8000912876517501943','VOC-0188',False),
        ('香港标准户型替代','T1-8000912876517501741','VOC-0180',True),
        ('香港实用面积不改建筑口径','T1-8000912876517501741','VOC-0186',False),
        ('香港套房总数不改主卧数量','T1-8000912876517501741','VOC-0210',False),
        ('香港石灰岩外墙保留','T1-8000912876517501741','VOC-0416',True),
        ('熙瑞文章噪音保留','T2-8000912876517502943','VOC-0157',True),
        ('噪音评论保持主题','T2-C-7963753211120747176','VOC-0157',True),
        ('明湖印外立面材料覆盖','T1-75149','VOC-0416',True)]
    evidence=[]
    for name,rid,tid,want in anchors:
        if rid not in current:continue
        evidence.append({'检查项':name,'来源ID':rid,'检查标签':tid,'期望':'保留/补出' if want else '不能打',
            '旧版符合':(tid in tags(previous,rid))==want,'本版符合':(tid in tags(current,rid))==want,
            '口径':'已知事实锚点回归，不是全量人工金标准或总体准确率'})
    measures=[]
    for label,p in [('上轮交付基线',old),('本轮全字典补选' if new.get('supplement_status') else '本轮字段完整性修复',new)]:
        product=p['tables']['产品信息单元'];views=p['tables']['观点信息单元'];allrows=product+views
        measures.append({'版本':label,'产品单元数':len(product),'文章观点数':sum(u['来源类型']=='文章' for u in views),
            '评论观点数':sum(u['来源类型']=='评论' for u in views),'无标签单元数':sum(not u['标签明细'] for u in allrows),
            '产品做法为空数':sum(not u['具体产品做法'] for u in product),'观点摘要为空数':sum(not u['观点摘要'] for u in views),
            '标签数':sum(len(u['标签明细']) for u in allrows),'未完成来源数':sum(not r['complete'] for r in p['results']),
            '未完成待核单元数':sum(len(r.get('pending_units',[])) for r in p['results']),
            '排除区间数':sum(len(r.get('excluded_intervals',[])) for r in p['results']),
            '原文复制异常数':sum(len(u.get('原文摘录',u.get('原始摘录','')))>40 and u.get('具体产品做法',u.get('观点摘要'))==u.get('原文摘录',u.get('原始摘录')) for u in allrows)})
    return {'anchor_checks':evidence,'measures':measures,'note':'无标签比例不是漏标率，标签数量不是准确率；只在同批来源比较完成情况和明确回归点。'}

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--input',type=Path,required=True);ap.add_argument('--prior',type=Path,required=True);ap.add_argument('--output-dir',type=Path,required=True)
    ap.add_argument('--taxonomy',type=Path,default=base.ROOT/'resources/置地VOC标签体系_两专题打标版.xlsx');a=ap.parse_args()
    p=json.loads(a.input.read_text(encoding='utf-8'));old=json.loads(a.prior.read_text(encoding='utf-8'));a.output_dir.mkdir(parents=True,exist_ok=True)
    if p.get('supplement_status'):
        p['supplement_call_costs']=supplement_costs(a.input.parent)
        if (a.input.parent/'token_cost_summary.json').exists():
            p['current_run_token_cost']=json.loads((a.input.parent/'token_cost_summary.json').read_text(encoding='utf-8'))
        from full_dictionary_supplement_v92 import evidence_catalog,audit_units,bind_evidence,unique_deferred
        for r in p['results']:
            original_deferred=r['label_supplement_deferred']
            r['label_supplement_deferred']=unique_deferred(original_deferred)
            r['label_supplement_coverage']['deferred_candidate_count']=len(r['label_supplement_deferred'])
            pending_pairs={(e['unit_id'],e.get('key')) for e in r['label_supplement_deferred']}
            r['label_supplement_coverage']['deferred_event_count']=sum((e.get('unit_id'),e.get('key')) in pending_pairs for e in r['label_supplement_events'])
            assert r['label_supplement_coverage']['deferred_event_count']>=len(pending_pairs)
            catalog=evidence_catalog(audit_units(r))
            for trace in r['traces']:
                for name in ['全字典补选证据','标签证据与归属']:
                    for proof in trace.get(name,[]):
                        if 'attribute_keys' in proof:
                            bind_evidence([proof],catalog)
                            assert not proof['_evidence_issues'],'Confirmed evidence IDs cannot be relocated'
                            for span in proof['attribute_spans']+proof['object_spans']:
                                assert r['document']['text'][span['start']:span['end']]==span['quote']
        p['supplement_status']['deferred_candidates']=sum(len(r['label_supplement_deferred']) for r in p['results'])
        p['supplement_status']['deferred_candidate_events']=sum(r['label_supplement_coverage']['deferred_event_count'] for r in p['results'])
    references,reference_source=reference_tables(a.taxonomy)
    for result in p['results']:
        result['rows']=enrich_rows(result['rows'],references[result['document']['topic']])
    for topic,kind in [(base.T1,'产品信息单元'),(base.T2,'观点信息单元')]:
        p['tables'][kind]=[u for r in p['results'] if r['document']['topic']==topic for u in r['rows']]
    p['delivery_label_reference']={'version':'v91-label-reference-display','source':reference_source,
        'counts':{topic:len(rows) for topic,rows in references.items()},
        'field':'标签明细之后新增标签强调方向；原JSON顺序去重、分号连接；不参与匹配与验收'}
    errors=[];ids=set();trace={t['unit_id']:t for r in p['results'] for t in r['traces']}
    for result in p['results']:
        doc=result['document']
        for row in result['rows']:
            t=trace[row['unit_id']]
            if row['unit_id'] in ids:errors.append('重复unit_id')
            ids.add(row['unit_id'])
            if doc['text'][t['起点']:t['终点']]!=row.get('原文摘录',row.get('原始摘录')):errors.append('原文定位错误')
            if doc['kind']=='评论' and (row['原始摘录']!=doc['text'] or row['映射文章id']!=(doc['row'].get('文章id') or None)):errors.append('评论切分/映射错误')
            if any(list(tag)!=base.TAG_KEYS for tag in row['标签明细']):errors.append('标签JSON八键错误')
            for h in ['热度指数','互动深度指数']:
                if row[h]!=base.numeric_score(doc['parent'].get(h)):errors.append('指数继承错误')
    if errors:raise ValueError(';'.join(set(errors)))
    stats=statistics(p['results']);assessment=evaluate(old,p);base.save_json(a.output_dir/'quality_comparison.json',assessment)
    base.save_json(a.output_dir/'final_contract_verification.json',{'passed':True,'sources':len(p['results']),'units':len(ids),'checks':['逐字原文','唯一ID','八键字典JSON','完整评论','评论平台文章ID映射','父文章ODS关联追溯','指数空值及零值继承']})
    base.write_csv(a.output_dir/'测试项目平台文章评论统计.csv',stats,list(stats[0]))
    packs=[];version=p.get('summary',{}).get('version','');joint=version.startswith('v95-');keyword=version.startswith(('v94-','v95-'));single=version.startswith(('v93-','v94-','v95-'));supplement=version.startswith(('v92-','v93-','v94-','v95-'));project_fix=version.startswith('v90-');current=version.startswith(('v89-','v90-','v92-','v93-','v94-','v95-'))
    for topic,kind,title in [(base.T1,'产品信息单元','产品信息单元_字段补全测试交付.xlsx' if current else '产品信息单元_保守纠错测试交付.xlsx'),(base.T2,'观点信息单元','观点信息单元_字段补全测试交付.xlsx' if current else '观点信息单元_文章与评论_保守纠错测试交付.xlsx')]:
        if project_fix:title=kind+'_项目上下文修复测试交付.xlsx'
        rs=[r for r in p['results'] if r['document']['topic']==topic];mainrows=[u for r in rs for u in r['rows']]
        source_rows=[{'record_id':d['record_id'],'源表id':d['source_id'],'来源类型':d['kind'],'父文章ODS主键':str(d['parent']['id']),
            '评论平台文章id':d['row'].get('文章id') if d['kind']=='评论' else None,'平台':d['row'].get('平台'),
            '内容类型':content_type(d),'主体字段':d['field'],'主体字数':len(d['text']),'原始主体':d['text'],
            '热度指数':base.numeric_score(d['parent'].get('热度指数')),'互动深度指数':base.numeric_score(d['parent'].get('互动深度指数')),
            '处理状态':'已完成' if r['complete'] else ('待核事项未全部解决' if supplement and r['label_supplement_coverage']['all_branches_checked'] else '有异常需人工审核'),'交付单元数':len(r['rows']),
            **({'文章标题':d.get('title'),'本轮项目归属核查':project_audit(r)} if project_fix or supplement else {}),
            **({'全字典标签数':r['label_supplement_coverage']['applicable_dictionary_count'],
                '全字典遍历完成':r['label_supplement_coverage']['all_branches_checked'],
                '全部候选审理完成':r['label_supplement_coverage']['all_candidates_adjudicated'],
                '新增标签数':r['label_supplement_coverage']['new_confirmed_tags'],
                '撤回错标数':r['label_supplement_coverage']['withdrawn_wrong_tags'],
                '候选待核数':r['label_supplement_coverage']['deferred_candidate_count'],
                '未解决事实数':len(r['label_supplement_coverage']['remaining_facts']),
                'API或合同异常':r['label_supplement_coverage']['errors']} if supplement else {})} for r in rs for d in [r['document']]]
        excluded=[{'record_id':r['document']['record_id'],'来源类型':r['document']['kind'],'父文章ODS主键':str(r['document']['parent']['id']),
            '平台':r['document']['row'].get('平台'),'原单元ID':e.get('原单元ID'),'起点':e.get('起点'),'终点':e.get('终点'),'原文':e['原文'],'排除原因':e['原因']} for r in rs for e in r.get('excluded_intervals',[])]
        human=[{'unit_id':u['unit_id'],'来源类型':r['document']['kind'],'原文':u.get('原文摘录',u.get('原始摘录')),'待审原因':u['备注'],
            '当前标签明细':u['标签明细'],'人工审核结果':'待审核','修改后标签明细':'','修改后摘要或做法':'','复核人':'','复核时间':''} for r in rs for u in r['rows'] if u['验收状态']=='需人工审核']
        pending=[]
        for r in rs:
            for q in r.get('pending_units',[]):
                pending.append({'unit_id':q['unit_id'],'record_id':q['record_id'],'来源类型':q['来源类型'],'原文':q['原文'],'起点':q['起点'],'终点':q['终点'],
                    '未完成原因':q['原因'],'旧标签明细':(q.get('旧单元') or {}).get('标签明细'),
                    '本轮候选标签':(q.get('补全候选') or {}).get('labels'),'本轮候选文案':(q.get('补全候选') or {}).get('rewrite'),
                    '人工审核结果':'待审核','修改后标签明细':'','修改后摘要或做法':'','复核人':'','复核时间':''})
                human.append({'unit_id':q['unit_id'],'record_id':q['record_id'],'来源类型':q['来源类型'],'原文':q['原文'],'待审原因':q['原因'],
                    '当前标签明细':(q.get('旧单元') or {}).get('标签明细'),'人工审核结果':'待审核','修改后标签明细':'','修改后摘要或做法':'','复核人':'','复核时间':''})
            if not r['complete']:human.append({'unit_id':None,'record_id':r['document']['record_id'],'来源类型':r['document']['kind'],'原文':r['document']['text'],
                '待审原因':('仍有候选、事实或历史待核事项，见补选覆盖和未解决事实记录。API/合同异常：'+('；'.join(r['label_supplement_coverage']['errors']) or '无') if supplement else '来源仍有处理异常：'+str(r.get('repair_errors') or r['audit'][-1].get('原因'))),
                '当前标签明细':None,'人工审核结果':'待审核','修改后标签明细':'','修改后摘要或做法':'','复核人':'','复核时间':''})
        sample_stats=[s for s in stats if s['项目']==topic]
        cost=[x for x in p['tables']['Token费用'] if x['专题']==topic]
        # The in-scope CSVs can have absent index values. This sheet counts them,
        # and never re-computes/reinterprets portal missing values as zero.
        summary={'文章入场数':sum(r['document']['kind']=='文章' for r in rs),'评论入场数':sum(r['document']['kind']=='评论' for r in rs),
            '交付单元数':len(mainrows),'有交付单元来源数':sum(bool(r['rows']) for r in rs),'确认无适用标签排除区间数':len(excluded),
            '未完成来源数':sum(not r['complete'] for r in rs),'未完成待核单元数':len(pending),'自动通过单元数':sum(u['验收状态']=='自动通过' for u in mainrows),'需人工审核单元数':sum(u['验收状态']=='需人工审核' for u in mainrows)}
        pack={'filename':title,'topic':topic,'summary':summary,'main_name':kind,'schemas':{kind:base.PRODUCT_FIELDS if topic==base.T1 else base.VIEW_FIELDS},
            'tables':{kind:mainrows,'测试渠道统计':sample_stats,'源记录与文章关联':source_rows,'排除区间':excluded,'人工审核':human,'历史批次Token费用':cost,
                '本轮修正与测试状态':[x for x in p.get('delivery_changes',[]) if x['unit_id'].startswith('T1-' if topic==base.T1 else 'T2-')]},
            'notes':['本文件基于上次完整80篇文章、113条评论测试批次；本轮新程序全批API重测未完成。','模型服务最小请求亦超时；只落实已知事实核查提案，全部主表单元仍需人工审核。','范围内行数是进入历史测试批次的源文章/评论数，不是切片数。','热度可计算数/互动可计算数表示源指数已有有效数值（零计入），本次没有重算。',
                '图文且视频只细分源字段原为图文且有视频链接的记录；视频封面图未擅自改类。','评论映射文章id采用评论CSV文章id；父文章真实ODS主键见源记录与文章关联。',
                '排除的是本版主表中的确认无适用标签区间，原始CSV没有删除。','历史批次Token费用包括多轮处理，不是本轮新增费用；未取得usage的中断请求费用未知。',
                '专题二微信视频号原始121条、可用主体0，本批文章评论均为0。' if topic==base.T2 else '抽样：微信公众号8、小红书8、视频号7、网页7，固定种子20261008。'],
            'comparison':assessment}
        if current:
            pack['tables']['未完成待核']=pending
            pack['notes']=['本轮在历史80篇文章、113条评论批次上做异常定向API补全；正常已有单元未全量语义重审。',
                '主表标签、打标说明及摘要/做法完整；未解决内容另列未完成待核，不能把移表后的完整率当作全批修复率。',
                '专题一只用产品字典；专题二允许品牌、土地配套、产品、交付、客户、服务等适用分支。',
                '范围内行数是源文章/评论数，不是切片数。指数保留源值，缺失不填零；所有源记录均保留。',
                '重复宣传、非适用内容移出主表但保存原文和排除理由；有意义的字典缺口或证据不确定保留待核。',
                '评论映射文章id采用评论CSV文章id；父文章真实ODS主键另存；一条有效评论完整一行。',
                '全部仍需人工审核；模型置信度不是实测准确率。累计Token包含历史批次，超32K及usage缺失价格未知。',
                '专题二视频号原始121条、主体可用0，本批为0。' if topic==base.T2 else '专题一：公众号8、小红书8、视频号7、网页7，种子20261008。']
        if project_fix:
            status=p['project_context_status']
            pack['notes']=['沿用同批80篇文章、113条评论；本轮只修复项目上下文漏填，未重新切片或重打标签。',
                f"观点主表原有空项目{status['before_empty']}条，本轮补齐{status['filled']}条，剩余{status['after_empty']}条。",
                f"剩余分为非研究项目{status['outside']}条、不指向具体研究项目{status['no_project']}条、证据/API待核{status['pending']}条。",
                '文章标题与主体分开保留；项目可继承连续对象范围，发生楼盘切换时不能沿用。',
                '文章与评论项目ID、名称、角色统一为位置对应JSON数组；字典名称及角色未由模型改写。',
                '父文章关联不等于评论项目归属；评论须有明确点名或同一项目话题关系。',
                '项目补齐的引文、位置、判断和置信度见源记录与文章关联的本轮项目归属核查列。',
                '原标签、摘要/做法、原文、评论文章映射和指数均保留；原有标签待核事项未宣称解决。',
                '全部仍需人工审核；历史批次Token费用包含本轮新增归属请求，未知usage不视为免费。',
                '专题二视频号原始121条、主体可用0，本批为0。' if topic==base.T2 else '专题一产品93条未改变，随本版重新导出。']
        if supplement:
            from evaluate_supplement_v92 import assess
            regressions=assess(old,p)['regression_checks']
            pack['tables']['已知案例回归']=[*assessment['anchor_checks'],
                *[{**x,'比较口径':'已知案例与结构回归，不是全量人工金标准'} for x in regressions]]
            comparison=[]
            for label,version_data in [('上轮原文关键词补标基线' if joint else '上轮单片分组交付基线' if keyword else 'v92全字典补选基线' if single else 'v91基线',old),('切片与已有标签联合补标' if joint else '单片分组加关键词兜底' if keyword else 'v93单片分组查漏' if single else 'v92全字典补选',p)]:
                same_topic=[r for r in version_data['results'] if r['document']['topic']==topic]
                units=[u for r in same_topic for u in r['rows']]
                comparison.append({'版本':label,'文章来源数':sum(r['document']['kind']=='文章' for r in same_topic),
                    '评论来源数':sum(r['document']['kind']=='评论' for r in same_topic),'交付单元数':len(units),
                    '标签数':sum(len(u['标签明细']) for u in units),
                    '标签说明文案缺失单元数':sum(not u['标签明细'] or not u['打标说明'] or not u.get('具体产品做法',u.get('观点摘要')) for u in units),
                    '未完成待核单元数':sum(len(r.get('pending_units',[])) for r in same_topic),
                    '全字典遍历完成来源数':sum(r['label_supplement_coverage']['all_branches_checked'] for r in same_topic) if version_data.get('supplement_status') else None,
                    '比较口径':'同批完成情况，不是人工金标准漏标率或精确率'})
            coverage=[]
            for r in rs:
                c=r['label_supplement_coverage']
                coverage.append({'record_id':r['document']['record_id'],'来源类型':r['document']['kind'],
                    '平台':r['document']['row'].get('平台'),'适用字典标签数':c['applicable_dictionary_count'],
                    '标签分组数':c['branch_count'],'扫描请求数':c['scan_request_count'],'已完成分组数':c['completed_branch_count'],
                    **({'请求方式':'单片 × 单标签组','每请求待打标单元数':1} if single else {}),
                    '字典遍历完成':c['all_branches_checked'],'全部候选审理完成':c['all_candidates_adjudicated'],
                    '待核候选数':c['deferred_candidate_count'],'待核候选历史事件数':c['deferred_event_count'],
                    '原始单元数':c['all_source_units'],'提议标签单元组合数':c['proposed_pairs'],
                    '新增标签数':c['new_confirmed_tags'],'撤回错标数':c['withdrawn_wrong_tags'],'恢复单元数':c['restored_units'],
                    '未解决事实数':len(c['remaining_facts']),'API或合同异常':'；'.join(c['errors']) or '无',
                    **({'关键词检查单元数':r['keyword_supplement_coverage']['target_units'],
                        '关键词遍历标签组合数':r['keyword_supplement_coverage']['checked_unit_label_pairs'],
                        '关键词直接补入标签数':r['keyword_supplement_coverage']['direct_added_pairs'],
                        '关键词待核候选数':r['keyword_supplement_coverage']['review_pairs']} if keyword else {}),
                    **({'联合检查单元数':r['joint_keyword_supplement_coverage']['target_units'],
                        '联合遍历标签组合数':r['joint_keyword_supplement_coverage']['checked_unit_label_pairs'],
                        '联合本轮直接补入标签数':r['joint_keyword_supplement_coverage'].get('new_this_invocation',0),
                        '联合待核候选数':r['joint_keyword_supplement_coverage']['review_pairs'],
                        '仅标签含属性不补标数':r['joint_keyword_supplement_coverage']['label_only_not_added_pairs']} if joint else {})})
            events=[{'record_id':r['document']['record_id'],'来源类型':r['document']['kind'],
                'unit_id':e.get('unit_id'),'标签路径ID':'VOC-'+e['key'][1:] if e.get('key') else None,
                '处理':e['处理'],'原因':e['原因'],'属性证据':e.get('quotes'),'对象上下文证据':e.get('context_quotes'),
                '事实对象':e.get('object'),'置信度':e.get('confidence'),'历史冲突处理':e.get('history_resolution'),
                **({'补标方法':e.get('decision_method','历史模型审核'),
                    '命中核心字眼':e.get('keyword_matches'), '关键词规则版本':e.get('rule_version')} if keyword else {}),
                **({'联合命中核心字眼':e.get('联合核心字眼'),'来源标签ID':e.get('source_label_id'),
                    '来源标签原文证据':e.get('source_label_proof'),'对象绑定方式':e.get('object_binding_method')} if joint else {}),
                '人工审核结果':'待审核','修改后标签明细':'','修改后摘要或做法':'','复核人':'','复核时间':''}
                for r in rs for e in r['label_supplement_events']]
            facts=[{'record_id':r['document']['record_id'],'unit_id':f['unit_id'],**(pending_fact_display(f,r) if single else {'原文证据':f['quotes'],'待核原因':f['reason']}),
                '未解决事实':f['fact'],'人工审核结果':'待审核','修改后标签明细':'',
                '修改后摘要或做法':'','复核人':'','复核时间':''} for r in rs for f in r['label_supplement_coverage']['remaining_facts']]
            for r in rs:
                for e in r['label_supplement_deferred']:
                    human.append({'unit_id':e['unit_id'],'record_id':r['document']['record_id'],'来源类型':r['document']['kind'],
                        '原文':next(u['text'] for u in __import__('full_dictionary_supplement_v92').audit_units(r) if u['unit_id']==e['unit_id']),
                        '待审原因':'补选候选待核：'+e['key']+'：'+e['原因'],'当前标签明细':None,
                        '人工审核结果':'待审核','修改后标签明细':'','修改后摘要或做法':'','复核人':'','复核时间':''})
            pack['tables'].update({'同批测试对照':comparison,'补选覆盖记录':coverage,'标签补选与纠错':events,'未解决事实':facts,
                '本轮补选Token费用':p.get('supplement_call_costs',{}).get(topic,[])})
            pack['summary'].update({'字典遍历完成来源数':sum(r['label_supplement_coverage']['all_branches_checked'] for r in rs),
                '新增标签数':sum(r['label_supplement_coverage']['new_confirmed_tags'] for r in rs),
                '撤回错标数':sum(r['label_supplement_coverage']['withdrawn_wrong_tags'] for r in rs),
                '新恢复单元数':sum(r['label_supplement_coverage']['restored_units'] for r in rs)})
            if single and p.get('current_run_token_cost'):
                costs=[x for x in p['current_run_token_cost']['by_topic_source'] if x['topic']==topic]
                pack['summary'].update({'本轮已知输入Token':sum(x['prompt_tokens'] for x in costs),
                    '本轮已知输出Token':sum(x['completion_tokens'] for x in costs),
                    '本轮已知缓存Token':sum(x['cached_input_tokens'] for x in costs),
                    '本轮已知估算费用元':sum(x['known_estimated_yuan'] for x in costs),
                    '本轮未知用量尝试数':sum(x['attempts_without_usage'] for x in costs)})
                for row in pack['tables']['本轮补选Token费用']:
                    row['价格口径']='元/百万Token：非缓存输入0.20、缓存输入0.04、输出0.80；输入>32000价格未知；程序估算，非账单'
            pack['notes']=['本轮在原80篇文章、113条评论上执行全字典分组API查漏，已完成字段的单元也重新检查。',
                ('每个请求仅一个切片与一组适用标签；只附有限身份/指代上下文，不能补片外属性；核验和替代补选也不混审其他切片。' if single else '完整原文输入每个标签分组；文章原语义边界保留，评论保持完整，不借父文章事实给评论补标。'),
                '文章原语义边界保留，评论整条一行；全文阶段用于切片，本轮不重新切片。',
                '有原文证据且通过真实定义核验的标签追加到原JSON；片内同一标签ID不重复，不跨不同事实删标签。',
                '原错标须查漏与定义核验均确认后单独撤回；错候选继续找替代，格式错误先修证据。',
                '前后意见冲突须解释原拒绝条件，未解决的候选和事实保留待核，不以标签数量证明准确率。',
                '未解决事实是模型提出的审核线索，含字典缺项、证据不足或可能已经覆盖的内容，不直接认定为漏标。候选待核数按单元与标签ID去重，完整多轮意见仍保留。',
                '主表理由和摘要/做法非空；未获确认的单元保留在待核区，不能将主表完整率视为全批修复率。',
                '来源遍历完成不等于候选全部审理完成，更不等于零漏标；全部主表仍需人工审核。',
                '指数、原文、评论文章映射和已有项目归属保留；新恢复的项目按有据上下文核验。',
                '本轮补选Token费用与历史累计分开；未知usage不是0元。标签字典来源与适用规则不改变。',
                '专题二视频号原始121条、主体可用0，本批为0。' if topic==base.T2 else '专题一：公众号8、小红书8、视频号7、网页7，种子20261008。']
        dictionary_name='专题一标签体系' if topic==base.T1 else '专题二标签体系'
        if keyword:
            pack['summary'].update({'关键词直接补标数':sum(r['keyword_supplement_coverage']['direct_added_pairs'] for r in rs),
                '关键词待核候选数':sum(r['keyword_supplement_coverage']['review_pairs'] for r in rs)})
            pack['tables']['本轮补选Token费用'].append({'来源类型':'文章与评论' if topic==base.T2 else '文章',
                '阶段':'字典强调方向关键词兜底（本地规则，无API请求）','实际请求记录数':0,'HTTP尝试数':0,'成功请求数':0,
                '已知输入Token':0,'已知缓存Token':0,'已知输出Token':0,'已知估算费用元':0,
                '未知usage或价格请求数':0,'未知usage的HTTP尝试数':0,'口径':'本地规则追加成本为0；不重复计算上轮API费用'})
            pack['notes']=['沿用上轮交付切片、项目、摘要及已有标签；新增关键词兜底，只追加，不重新切片、不拆评论。',
                '每个交付单元遍历全部适用标签强调方向；结合真实路径的空间对象和属性词匹配，同一原句且必要条件明确才直接补入。',
                '会所和泳池的共现不能借给公共公园，厨房空调不能借客厅空调；面积和数量须有对应对象数值，中文数值不排除。',
                '提问、否定、跨对象、历史定义争议、仅有宽泛词的候选转待核，不用关键词覆盖旧否决。规划/宣传等限定保留在原文证据。',
                '主表已有标签按ID去重，新增标签由原字典回填；补标方法、命中字眼、证据与规则版本见标签补选与纠错。',
                '本地关键词阶段无API调用，新增Token与费用均为0。此前模型请求不重新计费；人工审核和准确率限制保持不变。',
                '范围内行数为来源文章/评论数，不是切片数；原文、指数、源关联及字典页保留。',
                '关键词兜底不保证零漏标；本轮只处理已有交付主表，未自动恢复待核/排除单元。',
                '专题二视频号原始121条、主体可用0，本批为0。' if topic==base.T2 else '专题一：公众号8、小红书8、视频号7、网页7，种子20261008。']
        if joint:
            pack['summary'].pop('关键词直接补标数',None)
            pack['summary'].update({'原文关键词本轮直接补标数':sum(r['keyword_supplement_coverage']['new_this_invocation'] for r in rs),
                '联合关键词本轮直接补标数':sum(r['joint_keyword_supplement_coverage'].get('new_this_invocation',0) for r in rs),
                '联合关键词待核候选数':sum(r['joint_keyword_supplement_coverage']['review_pairs'] for r in rs),
                '仅标签含属性不补标数':sum(r['joint_keyword_supplement_coverage']['label_only_not_added_pairs'] for r in rs)})
            pack['tables']['本轮补选Token费用'][-1]['阶段']='切片与冻结已有标签联合关键词补标（本地规则，无API请求）'
            pack['notes']=['保留上轮切片、评论、项目、摘要、指数和旧标签；本轮只更新补标及其审核记录。',
                '每片原文与本轮开始时的已有标签共同遍历全部适用字典；标签路径和强调方向提供对象提示，不把编号或ID当成数值。',
                '新增标签的具体属性必须在本片原文出现；已有标签的对象须追溯到该标签原文证据，连续同对象才能补入。原文明确每间卧室都配备时，可覆盖已有对应卧室对象。',
                '本轮新增标签不继续作为下一次补标的依据，避免标签互相推导。联合命中字眼位置按切片或来源标签文本分别记录，正式证据按全文字符位置记录。',
                '只有标签文字含属性、原文没有对应事实时记录为不补标；跨空间、跨发言者、对象归属不清、历史否决未解决的候选转待核。',
                '片内按真实标签路径ID去重，由字典回填全部层级和编号；原标签不删，旧模型审核意见保留，不因为本轮新增就自动宣称通过验收。',
                '同批测试对照的新增数仅相对上轮交付计算，历史补标事件仍可追溯；待核候选数不是已确认漏标数。',
                '本地补标新增API请求0、输入输出Token0、费用0元，历史API费用不重复计入。本轮不声称零漏标或人工金标准准确率。',
                '本轮只处理当前主表，不自动恢复待核或排除单元；范围内行数是来源数，不是切片数。',
                '专题二视频号原始121条、主体可用0，本批为0。' if topic==base.T2 else '专题一：公众号8、小红书8、视频号7、网页7，种子20261008。']
        pack['filename']=kind+('_切片标签联合补标测试交付.xlsx' if joint else '_关键词兜底补标测试交付.xlsx' if keyword else '_单片分组全字典补选测试交付.xlsx' if single else '_全字典补选测试交付.xlsx' if supplement else '_标签对照审核交付.xlsx')
        pack['schemas'][kind]=display_schema(pack['schemas'][kind])
        pack['schemas'][dictionary_name]=REFERENCE_FIELDS
        pack['tables']={kind:mainrows,dictionary_name:references[topic],
            **{name:rows for name,rows in pack['tables'].items() if name!=kind}}
        pack['reference_source']=reference_source
        pack['notes']=[('本轮标签补选和纠错记录另列审核；保留标签强调方向列及对应专题字典页。' if supplement else '本轮仅新增标签强调方向列及对应专题字典页；原切片、标签JSON、打标说明、项目归属及审核状态均未修改。'),
            '标签强调方向按现有标签JSON顺序汇总，重复词去重、分号连接；该列不参与打标和验收判断。',
            reference_source['topic_rule'],*pack['notes']]
        payload=a.output_dir/(kind+'_workbook_payload.json');base.save_json(payload,pack);packs.append(str(payload))
        base.write_csv(a.output_dir/(kind+'.csv'),mainrows,pack['schemas'][kind])
    base.save_json(a.output_dir/'delivery_results.json',p)
    print(json.dumps({'payloads':packs,'statistics':stats,'comparison':assessment,'contract_passed':True},ensure_ascii=False),flush=True)

if __name__=='__main__':main()
