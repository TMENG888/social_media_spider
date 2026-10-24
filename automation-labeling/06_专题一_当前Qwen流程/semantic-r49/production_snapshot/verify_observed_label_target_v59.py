"""Independent actual-source anchors: same-label repetition and wrong objects."""
import argparse,json
from pathlib import Path

def inspect(data):
    sources={r['document']['record_id']:r for r in data.get('results',[])};checks=[]
    def add(name,ok,detail):checks.append({'check':name,'passed':bool(ok),'detail':detail})
    def tags(rows):return {t['标签路径ID'] for u in rows for t in u['标签明细']}
    r=sources.get('T2-8000912876517503117')
    add('同户型四居低密洋房来源存在',r is not None,'缺源不跳过')
    if r:
        count=sum('VOC-0169' in tags([u]) for u in r['rows'])
        add('同一户型洋房属性不因四居低密修饰重复标签',count==1,
            f'实读同一240㎡户型，四居与低密不改变物业形态为洋房；当前标签行数={count}')
        add('同一完整户型多设施仍允许多标签一行',any('4室2厅3卫' in u.get('原始摘录','')
            and '专属家政套房' in u.get('原始摘录','') for u in r['rows']),
            '不能为降低标签数把同一完整户型各设施拆成多行')
    r=sources.get('T2-2188228096999350274')
    add('园林标签对象比较文章存在',r is not None,'缺源不跳过')
    if r:
        gardens=[u for u in r['rows'] if '王府中式园林' in u.get('原始摘录','')]
        add('王府园林不靠归家礼序推定大门风格',bool(gardens) and 'VOC-0332' not in tags(gardens),
            '字典0332明确大门风格；原文这一范围讲园林，理由“通常始于大门”是行业推断')
        add('明示王府中式园林保留景观设计风格',bool(gardens) and 'VOC-0401' in tags(gardens),
            '0401才是字典中的景观规划/景观设计风格，不删除正确园林标签规避错误')
        modern=[u for u in r['rows'] if '三园十八景' in u.get('原始摘录','')]
        add('现代中式造园不打住宅精装整体设计',bool(modern) and 'VOC-0229' not in tags(modern),
            '0229要求住宅精装装修风格，此处现代中式明确修饰造园逻辑')
        add('明确现代中式造园不漏景观设计风格',bool(modern) and 'VOC-0401' in tags(modern),
            '源文取法颐和园打造三园十八景，不能错用精装标签代替景观风格')
    return {'checks':checks,'errors':[c['check'] for c in checks if not c['passed']],
            'scope':'实读两条源文章及当前字典的目标属性/对象错误，不是全样本精确率或召回率'}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('input',type=Path);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();r=inspect(json.loads(a.input.read_text(encoding='utf-8')))
    a.output.write_text(json.dumps(r,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'checked':len(r['checks']),'errors':r['errors']},ensure_ascii=False))
    raise SystemExit(bool(r['errors']))
