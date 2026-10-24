"""Read-only diagnosis of exact current-version checkpoints, not a final gate."""
import argparse
import json
from pathlib import Path
import delivery_v11 as p


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--sample',type=Path,required=True)
    parser.add_argument('--folder',type=Path,required=True)
    parser.add_argument('--report',type=Path,required=True)
    args=parser.parse_args()
    sample=json.loads(args.sample.read_text(encoding='utf-8'))
    taxonomy=p.p.base.load_taxonomy(p.p.v.legacy.TAXONOMY)
    business=p.p.base.load_business()
    implementation=p.p.base.digest({name:Path(__file__).with_name(name).read_text(encoding='utf-8') for name in p.IMPLEMENTATION_FILES})
    signature=p.p.base.digest({'version':p.VERSION,'implementation':implementation,'taxonomy':taxonomy,'business':business,
        'api_base_url':'http://127.0.0.1:3000','model':'qwen3.7-flash'})
    rows=[];missing=[];issues=[]
    for doc in sample['documents']:
        path=args.folder/'documents'/(p.p.base.digest({'signature':signature,'document':doc})+'.json')
        if not path.exists():missing.append(doc['record_id']);continue
        result=json.loads(path.read_text(encoding='utf-8'))
        rows.append(result)
        index=p.p.v.registry(taxonomy,doc['topic'])
        legal={t['tag_id'] for t in index.values()}
        if not result.get('complete'):issues.append({'record_id':doc['record_id'],'type':'处理未完成'})
        if doc['kind']=='评论' and len(result['rows'])>1:
            issues.append({'record_id':doc['record_id'],'type':'评论拆行'})
        for row in result['rows']:
            uid=row['unit_id'];quote=row.get('原文摘录',row.get('原始摘录'))
            if not isinstance(quote,str) or quote not in doc['text']:
                issues.append({'unit_id':uid,'type':'摘录无法原文定位'})
            if doc['kind']=='评论' and quote!=doc['text']:
                issues.append({'unit_id':uid,'type':'评论未完整保留'})
            value=row.get('具体产品做法',row.get('观点摘要'))
            if value is None or str(value).strip().lower() in {'','null','none','nan'}:
                issues.append({'unit_id':uid,'type':'摘要/做法缺失或伪空字符串','value':value})
            tags=row['标签明细'];ids=[t.get('标签路径ID') for t in tags]
            if len(ids)!=len(set(ids)) or set(ids)-legal:
                issues.append({'unit_id':uid,'type':'重复/非法标签','tags':ids})
            if not tags:issues.append({'unit_id':uid,'type':'空标签须核验相关性或遗漏，不能直接认定漏标'})
    report={'version':p.VERSION,'planned_sources':len(sample['documents']),'current_version_checkpoints':len(rows),
        'missing_record_ids':missing,'issues':issues,
        'note':'只读检查当前签名检查点。缺少来源表示未完成；语义正确性仍须逐项对照原文及定义。'}
    p.p.base.save_json(args.report,report)
    print(p.p.base.dumps({k:report[k] for k in ['version','planned_sources','current_version_checkpoints']}))
    print(p.p.base.dumps({'issues':len(issues),'missing_sources':len(missing)}))


if __name__=='__main__':main()
