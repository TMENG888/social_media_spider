"""One independently read actual comment; not a production keyword gate."""
import argparse,json,re
from pathlib import Path

def inspect(data):
    r=next((x for x in data.get('results',[]) if x['document']['record_id']=='T2-C-7963753211120747279'),None)
    checks=[]
    def add(name,ok,detail):checks.append({'check':name,'passed':bool(ok),'detail':detail})
    add('熙瑞西与西冉北比较评论来源存在',r is not None,'不能缺源跳过')
    if r:
        rows=r['rows']
        add('完整比较评论一行且有摘要',len(rows)==1 and rows[0].get('原始摘录')==r['document']['text']
            and bool(rows[0].get('观点摘要')),'未拆评论、未用空摘要规避对象核查')
        if len(rows)==1:
            summary=rows[0].get('观点摘要') or ''
            generalized=bool(re.search(r'噪音(?:总体)?差不多|噪音(?:总体)?相近|噪音(?:总体)?相同',summary))
            scoped=bool(re.search(r'熙瑞西|西地块',summary)) and bool(re.search(r'西冉北|北地块',summary))
            add('噪音相近不从西北地块扩大项目整体',bool(summary) and (not generalized or scoped),
                '原文只称熙瑞西地块与西冉北地块噪音总体差不多，东地块和南地块另有不同影响')
    return {'checks':checks,'errors':[c['check'] for c in checks if not c['passed']],
            'scope':'实际7279评论的已观察范围泛化错误，不是完整评论摘要准确率'}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('input',type=Path);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();r=inspect(json.loads(a.input.read_text(encoding='utf-8')))
    a.output.write_text(json.dumps(r,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'checked':len(r['checks']),'errors':r['errors']},ensure_ascii=False))
    raise SystemExit(bool(r['errors']))
