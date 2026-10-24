"""Read-only independent delivery contract audit; not an accuracy claim."""
import argparse
import json
from collections import Counter
from pathlib import Path
import delivery_v4 as v


def verify(data):
    errors=[]
    def check(ok,message):
        if not ok:errors.append(message)
    tables=data['tables'];results=data['results'];traces={r['unit_id']:r for r in tables['来源追溯']}
    documents={r['document']['record_id']:r for r in results}
    samples=data['sampling']['samples'];articles=[r for r in results if r['document']['kind']=='文章']
    comments=[r for r in results if r['document']['kind']=='评论']
    flexible=data['summary'].get('version','').startswith(('delivery-v11','delivery-v76'))
    manifest=data.get('execution_manifest') or {}
    if flexible:
        requested=manifest.get('requested_record_ids')
        check(isinstance(requested,list) and len(set(requested))==len(requested),'运行请求清单缺失或重复')
        check(isinstance(requested,list) and set(requested)==set(documents),'未覆盖独立运行请求清单')
        if manifest.get('scope')=='完整随机批':check(len(articles)==len(samples),'未覆盖随机样本的全部文章')
    else:check(len(articles)==80,'未覆盖80篇文章')
    expected_comments=sum(s['关联评论数'] for s in samples if s['专题']==v.T2)
    if not flexible or manifest.get('scope')=='完整随机批':check(len(comments)==expected_comments,'未覆盖抽样文章的全部关联评论')
    check(len(documents)==len(results),'来源重复处理')
    expected=({topic:Counter(s['平台'] for s in samples if s['专题']==topic) for topic in [v.T1,v.T2]} if flexible else
        {v.T1:{'微信公众号':8,'小红书':8,'微信视频号':7,'网页':7},v.T2:{'微信公众号':10,'小红书':30,'网页':10}})
    for topic,counts in expected.items():
        actual=Counter(r['document']['row']['平台'] for r in articles if r['document']['topic']==topic) if flexible else Counter(s['平台'] for s in samples if s['专题']==topic)
        if not flexible or manifest.get('scope')=='完整随机批':check(actual==counts,'渠道配额不符：'+topic)
    if not flexible:check(len({r['document']['parent']['id'] for r in comments})==30,'评论所属文章不是30篇')
    elif manifest.get('scope')=='完整随机批':
        check({r['document']['parent']['id'] for r in comments}=={s['源文章ODS主键'] for s in samples if s['专题']==v.T2 and s['关联评论数']},'有评论文章覆盖不符')
    all_units=[]
    for table,fields in [('产品信息单元',v.PRODUCT_FIELDS),('观点信息单元',v.VIEW_FIELDS)]:
        check(data.get('schemas',{}).get(table)==fields,'导出字段顺序不符：'+table)
        units=tables[table];all_units+=units
        for u in units:
            uid=u['unit_id'];check(set(u)==set(fields),'字段合同不符：'+uid)
            t=traces.get(uid)
            if not t:errors.append('缺少追溯：'+uid);continue
            doc=documents[t['record_id']]['document'];a,b=t['起点'],t['终点'];evidence=t['原文证据']
            check(doc['text'][a:b]==evidence,'原文定位不符：'+uid)
            field,text=v.choose_source(doc['parent'])
            if doc['kind']=='文章':check(doc['field']==field and doc['text']==text,'主体优先级不符：'+uid)
            if doc['kind']=='评论':
                if data['summary'].get('version','').startswith(('delivery-v5.1','delivery-v6','delivery-v7','delivery-v8','delivery-v11','delivery-v76')):
                    check(u['映射文章id']==(doc['row'].get('文章id') or None),'评论源表文章id不符：'+uid)
                    check(doc['row'].get('文章id')==doc['parent'].get('文章id'),'评论和父文章的平台文章id不符：'+uid)
                    check(doc['row'].get('平台')==doc['parent'].get('平台'),'评论和父文章平台不符：'+uid)
                    check(t['所属文章ODS主键']==str(doc['parent']['id']),'追溯父文章ODS主键不符：'+uid)
                else:
                    check(u['映射文章id']==str(doc['parent']['id']),'父文章ODS主键不符：'+uid)
                check(u['原始摘录']==doc['text'] and a==0 and b==len(doc['text']),'评论被拆分：'+uid)
                check(all(isinstance(u[k],list) for k in ['project_id','项目名称','项目角色']),'评论项目不是JSON数组：'+uid)
                check(len(u['project_id'])==len(u['项目名称'])==len(u['项目角色']),'评论项目数组错位：'+uid)
            elif table=='观点信息单元':check(u['映射文章id'] is None,'文章映射id应空：'+uid)
            for metric in ['热度指数','互动深度指数']:
                check(u[metric]==v.numeric_score(doc['parent'].get(metric)),'指数继承不符：'+uid)
            tags=u['标签明细'];check(len({t['标签路径ID'] for t in tags})==len(tags),'同片标签重复：'+uid)
            for tag in tags:check(list(tag)==v.TAG_KEYS,'标签八键合同不符：'+uid)
            if u['验收状态']=='自动通过':
                check(not t['校验问题'] and bool(t['模型语义校验']),'有问题却自动通过：'+uid)
                check(bool(tags),'无标签自动通过：'+uid)
                summary=u.get('具体产品做法') if table=='产品信息单元' else u.get('观点摘要')
                check(bool(summary),'空文案自动通过：'+uid)
            else:check(bool(u['备注']),'人工审核无原因：'+uid)
    check(len({u['unit_id'] for u in all_units})==len(all_units),'unit_id重复')
    check(all(len(r['rows'])<=1 for r in comments),'一评论多行')
    excerpt_keys=[(t['record_id'],t['起点'],t['终点']) for t in tables['来源追溯'] if t.get('unit_id')]
    check(len(set(excerpt_keys))==len(excerpt_keys),'同源同切片重复多行')
    summary={'contract_errors':errors,'checked_articles':len(articles),'checked_comments':len(comments),
             'checked_units':len(all_units),'automatic_pass':sum(u['验收状态']=='自动通过' for u in all_units),
             'manual_review':sum(u['验收状态']!='自动通过' for u in all_units),
             'comments_with_unit':sum(bool(r['rows']) for r in comments),
             'comments_excluded_or_failed':sum(not r['rows'] for r in comments),
             'article_source_fields':dict(Counter(r['document']['field'] for r in articles)),
             'incomplete_documents':[r['document']['record_id'] for r in results if not r['complete']],
             'multi_label_units':sum(len(u['标签明细'])>1 for u in all_units),
             'multi_project_comments':sum(len(u['project_id'])>1 for u in tables['观点信息单元'] if u['来源类型']=='评论'),
             'note':'只证明程序合同与关联一致性；语义准确率仍需人工独立评估。'}
    return summary


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('input',type=Path);p.add_argument('--output',type=Path);args=p.parse_args()
    result=verify(json.loads(args.input.read_text(encoding='utf-8')))
    if args.output:v.save_json(args.output,result)
    print(json.dumps(result,ensure_ascii=False,indent=2))
    raise SystemExit(bool(result['contract_errors']))
