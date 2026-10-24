"""Observed article-local short-name continuity regression, read-only."""
import argparse,json
from pathlib import Path

def inspect(data):
    found=[r for r in data.get('results',[]) if r['document']['record_id']=='T2-2188228096999350274']
    checks=[]
    def add(name,ok,detail):checks.append({'check':name,'passed':bool(ok),'detail':detail})
    add('固定对比来源存在',len(found)==1,'缺失来源不能证明对象继承正确')
    if found:
        r=found[0];text=r['document']['text']
        add('全文明确介绍候选全称', '建发海晏' in text,'实际全文已明确建发海晏，后文海晏为此篇对比的项目简称；不是按检索词猜项目')
        relevant=[row for row in r['rows'] if '海晏' in row.get('原始摘录','') and '臻澐' in row.get('原始摘录','')]
        lost=[]
        for row in relevant:
            ids=row.get('project_id') or []
            if isinstance(ids,str):ids=[ids]
            if not {'P01','C01'}<=set(ids):lost.append(row['unit_id'])
        add('明确双项目比较片不丢海晏归属',bool(relevant) and not lost,
            '逐片实读空间/精装均比较两个项目，但历史只保留P01；缺失单元='+','.join(lost))
    return {'checks':checks,'errors':[c['check'] for c in checks if not c['passed']],
            'scope':'固定一篇的实际明确项目简称承接，不是允许全局猜简称或把父文配置继承给评论'}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('input',type=Path);p.add_argument('--output',required=True,type=Path)
    a=p.parse_args();r=inspect(json.loads(a.input.read_text(encoding='utf-8')))
    a.output.write_text(json.dumps(r,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'checked':len(r['checks']),'errors':r['errors']},ensure_ascii=False))
    raise SystemExit(bool(r['errors']))
