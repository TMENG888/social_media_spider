"""Actual source theme checks, not production keyword slicing rules."""
import argparse
import json
from pathlib import Path


def verify(data):
    byid={r['document']['record_id']:r for r in data['results']};checks=[]
    rid='T2-8000912876517503108';r=byid.get(rid)
    if r is not None:
        terms=['容积率','距离地铁6号线五路居站','3公里内有解放军总医院']
        matches={term:[row['unit_id'] for row in r['rows'] if term in row.get('原始摘录','')] for term in terms}
        selected=[matches[t][0] if len(matches[t])==1 else None for t in terms]
        checks.append({'record_id':rid,'passed':all(selected) and len(set(selected))==3,
            'theme_rows':matches,'why':'产品规划指标、交通、医疗在原文中是三个独立介绍主题；不能因同项目全部合成一行'})
    else:checks.append({'record_id':rid,'passed':False,'why':'来源未完成'})
    for rid,r in byid.items():
        for group in (r.get('full_source_partition',{}).get('adjacent_group_audit') or {}).get('groups',[]):
            if len(group.get('unit_indices',[]))>1:
                valid=group.get('same_object') is True and group.get('same_topic') is True
                valid=valid and group.get('object_scope') not in {None,'same_project','project_overview'}
                checks.append({'record_id':rid,'passed':valid,'group':group,
                    'why':'模型多元素合并必须表达具体对象和主题，项目身份本身不是条件'})
    return {'checks':checks,'passed':all(c['passed'] for c in checks),
        'note':'来源主题锚点和合并协议检查，不能替代逐片人工语义金标准；不按这些词生成生产边界。'}


def main():
    p=argparse.ArgumentParser();p.add_argument('input',type=Path)
    p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    report=verify(json.loads(a.input.read_text(encoding='utf-8')))
    a.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False))
    if not report['passed']:raise SystemExit(1)


if __name__=='__main__':main()
