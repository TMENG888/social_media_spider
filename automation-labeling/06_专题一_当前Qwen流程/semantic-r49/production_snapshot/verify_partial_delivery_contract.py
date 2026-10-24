"""Completed-subset fields/trace checks; not Excel order or semantic accuracy."""
import argparse
import json
from pathlib import Path
import delivery_v4 as v


def verify(results):
    errors=[];count=0;seen=set()
    for r in results:
        doc=r['document'];traces={t.get('unit_id'):t for t in r['traces']}
        if doc['kind']=='评论' and len(r['rows'])>1:
            errors.append({'id':doc['record_id'],'error':'评论多行'})
        for row in r['rows']:
            count+=1;uid=row['unit_id'];issues=[]
            fields=v.PRODUCT_FIELDS if 'content_id' in row else v.VIEW_FIELDS
            # JSON member insertion order is not a spreadsheet column order.
            # The exporter explicitly uses schemas; saved workbook order must
            # be inspected separately after actual export.
            if set(row)!=set(fields):issues.append('字段集合不符')
            if uid in seen:issues.append('重复unit_id')
            seen.add(uid);trace=traces.get(uid)
            if not trace or doc['text'][trace['起点']:trace['终点']]!=trace['原文证据']:
                issues.append('证据位置不符')
            if doc['kind']=='评论':
                if row['原始摘录']!=doc['text']:issues.append('评论不完整')
                if row['映射文章id']!=(doc['row'].get('文章id') or None):issues.append('映射原始文章id不符')
                if not all(isinstance(row.get(k),list) for k in ('project_id','项目名称','项目角色')):
                    issues.append('评论项目字段不是数组')
                elif len({len(row[k]) for k in ('project_id','项目名称','项目角色')})!=1:
                    issues.append('评论项目数组错位')
            elif 'record_id' in row and row['映射文章id'] is not None:
                issues.append('文章映射id不为空')
            for k in ('热度指数','互动深度指数'):
                if row[k]!=v.numeric_score(doc['parent'].get(k)):issues.append('指数继承不符:'+k)
            tags=row['标签明细']
            if len({t['标签路径ID'] for t in tags})!=len(tags):issues.append('同片重复标签')
            if any(list(t)!=v.TAG_KEYS for t in tags):issues.append('标签八键合同不符')
            if row['验收状态']=='自动通过':
                prose=row.get('具体产品做法') if 'content_id' in row else row.get('观点摘要')
                if not tags or not prose or trace and trace.get('校验问题'):
                    issues.append('有未完成项却自动通过')
            elif not row.get('备注'):issues.append('人工审核没有原因')
            if issues:errors.append({'unit_id':uid,'errors':issues})
    return {'checked_sources':len(results),'checked_units':count,'errors':errors,
            'scope':'已完成子集字段集合、证据位置、完整评论、数组对应及指数继承；不证明全批完成、Excel列序或语义精确率'}


def main():
    p=argparse.ArgumentParser();p.add_argument('documents',type=Path)
    p.add_argument('--output',type=Path,required=True);args=p.parse_args()
    results=[json.loads(f.read_text(encoding='utf-8')) for f in args.documents.glob('*.json')]
    report=verify(results);v.save_json(args.output,report);print(v.dumps(report))
    raise SystemExit(bool(report['errors']))


if __name__=='__main__':main()
