"""Read-only anchors from actual new full-batch rows, not production rules."""
import argparse,json
from pathlib import Path

def inspect(data):
    records={r['document']['record_id']:r for r in data.get('results',[])};checks=[]
    def add(name,passed,detail):checks.append({'check':name,'passed':bool(passed),'detail':detail})
    # This anchor is 7418 in the actual CSV; do not substitute the preceding ID.
    r=records.get('T2-C-7963753211120747418')
    add('750米评论实际来源存在',r is not None,'缺失不可跳过')
    if r:
        rows=r.get('rows',[])
        add('750米评论保持完整单行',len(rows)==1 and rows[0]['原始摘录']==r['document']['text'],
            '主评和架桥回复仍在同一行')
        if len(rows)==1:
            u=rows[0]
            add('主评角色不借回复机构身份',u.get('发布者角色')=='不明',
                '主评小白薯没有职业证明；机构账号是子回复，不是主评作者')
            add('父文身份及距离关系不因分句丢项目','保利熙瑞' in (u.get('项目名称') or []),
                '父文明确保利熙瑞及五路居750米，评论正问距离并回复架桥；须独立核对象而非候选数强继承')
    r=records.get('T2-C-7963753211120747422')
    add('营销引流评论实际来源存在',r is not None,'缺失不可跳过')
    if r:
        add('领取资料引流不变真实客户需求',not r['rows'] or all(
            '需求提问' not in (u.get('表达类型') or '') and
            'VOC-0053' not in {t['标签路径ID'] for t in u['标签明细']} for u in r['rows']),
            '可以有据排除，或保留并明确营销性质；不能凭领取资料推断购房动机')
    r=records.get('T1-2944395937563134382')
    add('招商百川序实际来源存在',r is not None,'缺失不可跳过')
    if r:
        rows=r['rows']
        add('明确招商品牌不因案名分隔符全部丢失',bool(rows) and all(u.get('品牌组')=='招商' for u in rows),
            '全文为招商·百川序及招商蛇口单项目介绍，不能因后片未重复品牌全部待判断')
        add('明确百川序项目身份保留',bool(rows) and all('百川序' in (u.get('项目') or '') for u in rows),
            '应保存原样招商·百川序或有独立证据的案名；不默许模型改写名称')
    return {'checks':checks,'errors':[c['check'] for c in checks if not c['passed']],
            'scope':'三条实际新样本的身份及营销锚点，不是完整金标准准确率'}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('input',type=Path);p.add_argument('--output',required=True,type=Path)
    a=p.parse_args();report=inspect(json.loads(a.input.read_text(encoding='utf-8')))
    a.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'checked':len(report['checks']),'errors':report['errors']},ensure_ascii=False))
    raise SystemExit(bool(report['errors']))
