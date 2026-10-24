"""Rule-first, evidence-checked multi-label delivery with parent-post score mapping.

Offline mode exports RULE candidates, never pretends to be an API test.
No database writes. Stable IDs distinguish post/comment sources.
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
import re
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal, InvalidOperation
from pathlib import Path
from multilabel_v2 import (T1, T2, choose_source, clause_spans, semantic_spans, label_guard,
                          load_taxonomy, sentiment, run_api_document, calculate_cost, summary_guard)

VERSION = 'rule-first-multilabel-v3-20261008'
REMOVED_FIELDS = {'标签属性','标签备注','产品体系','产品系标签','阅读/播放','点赞','收藏','评论','转发','互动量',
                  '明确评价标记','正负评价标记','需求提问标记','标签路径ID','一级标签','二级标签','三级标签','四级标签','五级标签'}
DELIVERY_FIELDS = ['所属专题','来源类型','源表id','映射文章id','文章平台id','来源评论id','切片ID','机器校验状态',
                   '项目','项目匹配状态','平台','发布日期','原始摘录','证据起点','证据终点','观点摘要','标签明细',
                   '热度指数','互动深度指数','映射状态','品牌组','经营主体','城市','产品档','产品系匹配状态',
                   '创新类型','创新等级','创新依据','处理方式','复核原因','人工验收状态']
GENERIC_TERMS = {'产品','客户','服务','土地','市场','品牌','通用','其他','整体','尺度','面积','数量','格局','位置','风格','功能','属性','布局'}
FACT_CUE = re.compile(r'\d|交付|精装|户型|空调|地暖|新风|净水|智能|冰箱|衣柜|厨房|主卧|次卧|噪声|采光|物业|价格|配套|交通|学校|公园|通风')


def read_csv(path: Path):
    with path.open(encoding='utf-8-sig',newline='') as f:
        return list(csv.DictReader(f))


def numeric_score(value):
    if value is None or str(value).strip().lower() in {'','null','none','nan'}:
        return None
    try:
        num = Decimal(str(value).strip())
        return float(num) if num.is_finite() and 0 <= num <= 100 else None
    except InvalidOperation:
        return None


class PostIndex:
    """Exact matching only. Ambiguous/conflicting joins stay unresolved."""
    def __init__(self, posts):
        self.pk, self.platform_id, self.platform_url = defaultdict(list), defaultdict(list), defaultdict(list)
        for p in posts:
            self.pk[str(p.get('id','')).strip()].append(p)
            platform = str(p.get('平台') or '').strip()
            for index, field in [(self.platform_id,'文章id'),(self.platform_url,'文章链接')]:
                value = str(p.get(field) or '').strip()
                if platform and value:
                    index[(platform,value)].append(p)

    def map_comment(self, comment):
        direct = str(comment.get('source_post_id') or comment.get('映射文章id') or '').strip()
        platform = str(comment.get('平台') or '').strip()
        matches = []
        if direct:
            matches.extend(self.pk.get(direct,[]))
        for index, field in [(self.platform_id,'文章id'),(self.platform_url,'文章链接')]:
            value = str(comment.get(field) or '').strip()
            if platform and value:
                matches.extend(index.get((platform,value),[]))
        unique = {str(p['id']):p for p in matches}
        if len(unique) != 1:
            return None, '未映射' if not unique else '多文章匹配或ID/链接冲突，待复核'
        parent = next(iter(unique.values()))
        if len(self.pk[str(parent['id'])])!=1:
            return None,'文章ODS主键在输入中重复，待复核'
        if direct and str(parent['id']) != direct:
            return None,'显式文章主键与关联结果冲突，待复核'
        if platform and parent.get('平台') and platform != str(parent['平台']).strip():
            return None,'评论与文章平台冲突，待复核'
        return parent,'唯一匹配所属文章'


def emphasis_terms(tag):
    terms=[]
    # Emphasis first, deepest term supplements it; no cap on exact matches.
    for text in [tag.get('emphasis',''),next((tag.get('l'+str(i)) for i in range(5,0,-1) if tag.get('l'+str(i))), '')]:
        for value in re.split(r'[、，,；;|/（）()]+',str(text or '')):
            value=value.strip()
            if len(value)>=2 and value not in GENERIC_TERMS and value not in terms:
                terms.append(value)
    return terms


def keyword_match(text, topic, taxonomy):
    matched, rejected, uncertain=[] ,[],[]
    for tag in taxonomy:
        if topic not in tag.get('topics',[]):
            continue
        hits=[term for term in emphasis_terms(tag) if term in text]
        if not hits:
            continue
        state,reason=label_guard(text,tag)
        entry={'tag':tag,'hits':hits,'reason':reason}
        if state=='rejected':
            rejected.append(entry)
        elif state=='uncertain' or tag.get('l1')=='客户':
            # Keywords cannot establish who holds the need/attitude.
            uncertain.append(entry)
        else:
            # Evidence includes its local clause, not merely an isolated word.
            evidence=next((text[a:b] for a,b in clause_spans(text) if any(h in text[a:b] for h in hits)), hits[0])
            matched.append({'tag_id':tag['tag_id'],**{k:tag.get(k) for k in ['l1','l2','l3','l4','l5','instruction']},
                            'evidence':evidence,'sentiment':sentiment(evidence),'machine_status':'规则证据通过，待验收',
                            'method':'标签强调方向/最深层词规则','issues':[]})
    # A hit is not proof of completeness: inspect each unmatched factual clause.
    uncovered=[]
    for a,b in clause_spans(text):
        clause=text[a:b]
        if len(clause.strip('，。；： '))>=8 and FACT_CUE.search(clause) and not any(t['evidence']==clause for t in matched):
            uncovered.append({'start':a,'end':b,'text':clause})
    return matched,rejected,uncertain,uncovered


def make_doc(row, source_type='文章', parent=None, mapping='文章自身'):
    parent=row if source_type=='文章' else parent
    source,text=choose_source(row) if source_type=='文章' else ('评论内容',row.get('评论内容') or '')
    topic=row.get('项目') or (parent or {}).get('项目')
    return {'article_id':('P:' if source_type=='文章' else 'C:')+str(row['id']),
            'source_id':str(row['id']),'source_type':source_type,'source':source,'text':text,
            'title':(parent or {}).get('文章标题',''),'topic':topic,
            'parent':parent,'row':row,'mapping':mapping}


def attach_delivery(doc, item):
    parent=doc.get('parent') or {}
    labels=[]
    for tag in item.get('labels',[]):
        labels.append({'标签路径ID':tag['tag_id'],**{name+'标签':tag.get('l'+str(i)) or None for i,name in enumerate(['一级','二级','三级','四级','五级'],1)},
                       '对应证据':tag['evidence'],'情绪方向':tag.get('sentiment'),
                       '打标方式':tag.get('method','大模型语义补标'),'机器状态':tag.get('machine_status'),
                       '复核说明':'；'.join(tag.get('issues',[]))})
    sid=hashlib.sha256(f"{doc['source_type']}|{doc['source_id']}|{doc['topic']}|{item.get('project','')}|{item['start']}|{item['end']}|{item['excerpt']}".encode()).hexdigest()[:24]
    score_issues=[]
    if not parent:
        score_issues.append('没有唯一映射文章，两个指数不可继承')
    elif any(numeric_score(parent.get(k)) is None for k in ['热度指数','互动深度指数']):
        score_issues.append('所属文章部分指数缺失或无效，保持NULL；未在切片层重算')
    issues=list(dict.fromkeys(item.get('issues',[])+score_issues))
    if not labels:
        issues.append('没有有效标签：待补标或排除')
    return {'所属专题':doc['topic'],'来源类型':doc['source_type'],'源表id':doc['source_id'],
            '映射文章id':str(parent['id']) if parent else None,'文章平台id':parent.get('文章id') or None,
            '来源评论id':doc['row'].get('评论id') if doc['source_type']=='评论' else None,
            '切片ID':sid,'机器校验状态':'需人工复核' if issues or any(t.get('issues') for t in item.get('labels',[])) else '机器证据通过，待人工验收',
            '项目':item.get('project') or '待判断','项目匹配状态':item.get('project_status','待字典核验'),
            '平台':doc['row'].get('平台') or parent.get('平台'),'发布日期':doc['row'].get('评论时间') if doc['source_type']=='评论' else parent.get('文章时间地点'),
            '原始摘录':item['excerpt'],'证据起点':item['start'],'证据终点':item['end'],
            '观点摘要':item.get('summary') or '', '标签明细':labels,
            '热度指数':numeric_score(parent.get('热度指数')),'互动深度指数':numeric_score(parent.get('互动深度指数')),
            '映射状态':doc['mapping'],'品牌组':None,'经营主体':None,'城市':None,'产品档':None,'产品系匹配状态':'待字典核验',
            '创新类型':None,'创新等级':None,'创新依据':None,'处理方式':item.get('method','规则先行＋大模型补标'),
            '复核原因':'；'.join(issues),'人工验收状态':'待人工验收'}


def process_document(doc, taxonomy, mode, base_url, model):
    slices,ledger,calls,errors=[],[],[],[]
    if not doc['text'].strip():
        return {'document':doc,'slices':[],'ledger':[],'calls':[],'errors':['无可用文本']}
    for a,b in semantic_spans(doc['text']):
        excerpt=doc['text'][a:b]
        rules,rejected,uncertain,uncovered=keyword_match(excerpt,doc['topic'],taxonomy)
        reasons=[]
        if not rules: reasons.append('没有强规则标签')
        if uncertain: reasons.append('客户主体/词面或对象不确定')
        if uncovered: reasons.append('存在未覆盖事实句段')
        if sentiment(excerpt)=='正负混合': reasons.append('存在混合情绪')
        if len(excerpt)>40: reasons.append('需要独立摘要，不静默复制长原文')
        rule_item={'start':a,'end':b,'excerpt':excerpt,'summary':excerpt if len(excerpt)<=40 else '',
                   'project':'','project_status':'待字典核验','labels':rules,'issues':[], 'method':'规则先行'}
        # API is only called for failed/partial rule matching or semantic/summary uncertainty.
        use_api=mode=='api' and bool(reasons)
        entry={'来源类型':doc['source_type'],'源表id':doc['source_id'],'所属专题':doc['topic'],
               '起点':a,'终点':b,'规则标签ID':[t['tag_id'] for t in rules],
               '规则排除ID':[x['tag']['tag_id'] for x in rejected],
               '不确定候选ID':[x['tag']['tag_id'] for x in uncertain],
               '未覆盖句段':[x['text'] for x in uncovered], '补标触发原因':reasons,'API已调用':use_api}
        if use_api:
            context=doc['title']+' '+doc['text'][max(0,a-300):a]
            if doc['source_type']=='评论':
                context+=' '+str((doc.get('parent') or {}).get('文章内容') or '')[:800]
            api_doc=dict(doc,text=excerpt,title=doc['title'],reference_context=context)
            result=run_api_document(api_doc,taxonomy,base_url,model)
            calls.extend(result['calls']);errors.extend(result['issues'])
            if result['state'] in {'api_failed','partial_failed','invalid_response'}:
                rule_item['issues'].append('API失败或格式不完整；规则结果仅作为候选保留')
            if result['slices']:
                for item in result['slices']:
                    if result['issues']:
                        item['issues'].extend(result['issues'])
                    ids={x['tag_id'] for x in item['labels']}
                    denied={str(x.get('tag_id')) for x in item.get('rejected_labels',[])}
                    for rule in rules:
                        if rule['tag_id'] in denied:
                            item['issues'].append('规则与模型标签冲突：'+rule['tag_id'])
                        elif rule['tag_id'] not in ids and rule['evidence'] in item['excerpt']:
                            item['labels'].append(rule)
                            ids.add(rule['tag_id'])
                    item['start']+=a;item['end']+=a
                    item['method']='规则先行＋大模型补标'
                    assert doc['text'][item['start']:item['end']]==item['excerpt']
                    slices.append(attach_delivery(doc,item))
                retained={t['标签路径ID'] for s in slices if s['证据起点']>=a and s['证据终点']<=b for t in s['标签明细']}
                lost=[t['tag_id'] for t in rules if t['tag_id'] not in retained]
                if lost:
                    entry['未保留规则标签']=lost
                    lost_reason='规则标签未被最终证据接纳，需复核：'+','.join(lost)
                    errors.append(lost_reason)
                    for s in slices:
                        if s['证据起点']>=a and s['证据终点']<=b:
                            s['机器校验状态']='需人工复核'
                            s['复核原因']='；'.join(filter(None,[s['复核原因'],lost_reason]))
            elif result['state']=='excluded':
                entry['排除原因']='；'.join(result['issues']) or 'API判定无有效内容'
                if rules:
                    rule_item['issues'].append('模型排除与规则命中冲突，保留候选供人工复核')
                    slices.append(attach_delivery(doc,rule_item))
            else:
                rule_item['issues'].append('API未得到可验证切片，原始规则候选待复核')
                slices.append(attach_delivery(doc,rule_item))
        elif rules or uncertain or uncovered:
            rule_item['issues'].extend(reasons)
            if mode=='offline': rule_item['issues'].append('离线规则测试，未调用大模型；不是最终打标结果')
            slices.append(attach_delivery(doc,rule_item))
        else:
            entry['排除原因']='没有匹配标签或有效事实，待复核排除；不强行制造单元'
        ledger.append(entry)
    # Stable IDs and one label array per exact source slice, not one row per tag.
    merged={}
    for row in slices:
        key=row['切片ID']
        if key not in merged: merged[key]=row
        else:
            by_tag={t['标签路径ID']:t for t in merged[key]['标签明细']}
            by_tag.update({t['标签路径ID']:t for t in row['标签明细']})
            merged[key]['标签明细']=list(by_tag.values())
            merged[key]['复核原因']='；'.join(filter(None,[merged[key]['复核原因'],row['复核原因']]))
    return {'document':doc,'slices':list(merged.values()),'ledger':ledger,'calls':calls,'errors':errors}


def export_result(output, results, taxonomy_path, input_path, mode):
    output.mkdir(parents=True,exist_ok=True)
    rows=[s for r in results for s in r['slices']]
    calls=[c for r in results for c in r['calls']]
    costs=[calculate_cost(c.get('prompt_tokens'),c.get('cached_input_tokens'),c.get('completion_tokens')) for c in calls]
    stats={'mode':mode,'version':VERSION,'source_posts':sum(r['document']['source_type']=='文章' for r in results),
           'source_comments':sum(r['document']['source_type']=='评论' for r in results),
           'posts_by_topic':dict(Counter(r['document']['topic'] for r in results if r['document']['source_type']=='文章')),
           'slices':len(rows),'label_associations':sum(len(s['标签明细']) for s in rows),
           'heat_mapped_slices':sum(s['热度指数'] is not None for s in rows),'depth_mapped_slices':sum(s['互动深度指数'] is not None for s in rows),
           'api_calls':len(calls),'known_cost_yuan':sum(c for c in costs if c is not None),'unknown_usage_calls':sum(c is None for c in costs),
           'tokens':sum(c.get('total_tokens') or 0 for c in calls),'human_accepted':0,
           'quality_note':'规则命中、API成功和人工验收分开；本统计不是准确率/漏标率。文章指数继承到切片，汇总时按映射文章id去重，不按切片求和。'}
    tables={}
    for source in ['文章','评论']:
        for topic,kind in [(T1,'产品'),(T2,'观点')]:
            name=source+kind+'信息单元'
            subset=[s for s in rows if s['所属专题']==topic and s['来源类型']==source]
            tables[name]=subset
            write_csv(output/(name+'.csv'),subset,DELIVERY_FIELDS)
    reviews=[{'所属专题':r['document']['topic'],'来源类型':r['document']['source_type'],'源表id':r['document']['source_id'],
              '切片ID':s['切片ID'],'原始摘录':s['原始摘录'],'复核原因':s['复核原因'],
              '人工复核结果':'待人工验收','修改后摘要':'','修改后标签明细':'','复核人':'','复核时间':''}
             for r in results for s in r['slices']]
    reviews.extend({'所属专题':r['document']['topic'],'来源类型':r['document']['source_type'],'源表id':r['document']['source_id'],
                    '切片ID':None,'原始摘录':None,'复核原因':'；'.join(r['errors']) or '没有切片输出；核验原文与排除原因',
                    '人工复核结果':'待人工验收'} for r in results if not r['slices'] or r['errors'])
    tables['需人工复核']=reviews
    write_csv(output/'04_需人工复核.csv',reviews,['所属专题','来源类型','源表id','切片ID','原始摘录','复核原因','人工复核结果','修改后摘要','修改后标签明细','复核人','复核时间'])
    ledger=[l for r in results for l in r['ledger']]
    tables['覆盖检查']=ledger
    write_csv(output/'覆盖检查.csv',ledger)
    # Full immutable source context remains in audit JSON, not in the slim delivery schema.
    data={'summary':stats,'tables':tables,'results':results,'source_csv':str(input_path),'taxonomy_path':str(taxonomy_path),
          'taxonomy_sha256':hashlib.sha256(Path(taxonomy_path).read_bytes()).hexdigest(),
          'price_note':'用户提供实时档：输入0.2/缓存0.04/输出0.8元每百万Token；超过32K输入费用未知，未确认账单价格'}
    (output/'refactor_results.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    return data


def write_csv(path, rows, fields=None):
    fields=fields or list(dict.fromkeys(k for r in rows for k in r)) or ['说明']
    with path.open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore');writer.writeheader()
        for row in rows:
            writer.writerow({k:json.dumps(v,ensure_ascii=False) if isinstance(v,(list,dict)) else v for k,v in row.items()})


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',type=Path,required=True)
    parser.add_argument('--config',type=Path,required=True)
    parser.add_argument('--output-dir',type=Path,required=True)
    parser.add_argument('--taxonomy',type=Path,default=Path(__file__).parent/'resources/置地VOC标签体系_两专题打标版.xlsx')
    parser.add_argument('--comments',type=Path)
    parser.add_argument('--comment-limit-per-topic',type=int,default=10)
    parser.add_argument('--mode',choices=['api','offline'],default='api')
    parser.add_argument('--api-base-url',default='http://127.0.0.1:3000')
    parser.add_argument('--model',default='qwen3.7-flash')
    parser.add_argument('--concurrency',type=int,default=4)
    args=parser.parse_args()
    if not 1<=args.concurrency<=16 or args.comment_limit_per_topic<0: parser.error('invalid concurrency/comment limit')
    if args.mode=='api':
        from llm_api_client import LlmApiClient
        LlmApiClient(args.api_base_url,args.model).session.close()
    taxonomy=load_taxonomy(args.taxonomy)
    posts=read_csv(args.input)
    config=json.loads(args.config.read_text(encoding='utf-8-sig'))
    wanted=config['sample_ids']
    chosen=[p for p in posts if str(p['id']) in set(wanted)]
    selected={str(p['id']):p for p in chosen}
    if len(chosen)!=len(selected): raise ValueError('Duplicate source article primary keys')
    if len(selected)!=len(set(wanted)) or len(set(wanted))!=len(wanted): raise ValueError('missing/duplicate selected article IDs')
    documents=[make_doc(selected[k]) for k in wanted]
    if any(d['topic'] not in {T1,T2} for d in documents): raise ValueError('article outside target topics')
    comment_audit=Counter()
    if args.comments:
        index=PostIndex(posts);counts=Counter()
        for comment in read_csv(args.comments):
            comment_audit['读取评论数']+=1
            parent,status=index.map_comment(comment)
            if not parent:
                comment_audit['未唯一映射评论数']+=1
                continue
            if str(parent['id']) not in selected:
                comment_audit['不属于本批抽样文章的评论数']+=1
                continue
            if parent and str(parent['id']) in selected:
                topic=parent.get('项目')
                if topic in {T1,T2} and counts[topic]<args.comment_limit_per_topic:
                    if comment.get('项目') and comment['项目']!=topic:
                        comment_audit['评论专题与文章专题冲突数']+=1
                        continue
                    doc=make_doc(comment,'评论',parent,status)
                    documents.append(doc);counts[topic]+=1
                    comment_audit['纳入测试评论数']+=1
                else:
                    comment_audit['超过本批评论抽样上限数']+=1
    started=time.perf_counter()
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        results=list(pool.map(lambda d:process_document(d,taxonomy,args.mode,args.api_base_url,args.model),documents))
    data=export_result(args.output_dir,results,args.taxonomy,args.input,args.mode)
    stats=data['summary'];stats['elapsed_seconds']=round(time.perf_counter()-started,3)
    stats['comment_mapping_audit']=dict(comment_audit)
    (args.output_dir/'refactor_results.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(stats,ensure_ascii=False))


if __name__=='__main__':
    main()
