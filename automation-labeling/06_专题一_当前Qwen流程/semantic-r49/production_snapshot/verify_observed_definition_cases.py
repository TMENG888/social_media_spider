"""Source-specific confirmed definition risks, not a precision/recall claim."""
import argparse
import json
from pathlib import Path
from prose_source_constraints import issues as prose_issues


def inspect(data):
    results={r['document']['record_id']:r for r in data.get('results',[])};checks=[]
    def add(name,okay,detail):checks.append({'check':name,'passed':bool(okay),'detail':detail})
    rid='T1-7868135928622720541';r=results.get(rid)
    add(rid+'真实来源存在',r is not None,'不能用未检查冒充通过')
    if r:
        batches=[u for u in r['rows'] if '共计95套' in u.get('原文摘录','')]
        add('本次95套推售不冒充项目总户数',bool(batches) and all(
            not any(t['标签路径ID']=='VOC-0167' for t in u['标签明细']) for u in batches),
            '原文明示本次加推而非项目总图总户数；必须保留有据的面积等信息')
        gyms=[u for u in r['rows'] if '健身房' in u.get('原文摘录','')]
        add('只有健身房不推断具体器械叶子',bool(gyms) and all(
            not any(t['标签路径ID']=='VOC-0377' for t in u['标签明细'])
            or any(w in u['原文摘录'] for w in ('器械','器材','跑步机','力量训练设备')) for u in gyms),
            '本条真实原文只列会所健身房、瑜伽等功能，不明确器械；不是所有健身房信息都无关')
    rid='T1-75278';r=results.get(rid)
    add(rid+'真实来源存在',r is not None,'不能用未检查冒充通过')
    if r:
        facilities=[u for u in r['rows'] if '老年活动场站' in u.get('原文摘录','')]
        add('配建场站不冒充景观活动区',bool(facilities) and all(
            not any(t['标签路径ID']=='VOC-0412' for t in u['标签明细']) for u in facilities),
            '当前地块配建场站原文没有社区景观活动区的明确对象')
    rid='T1-75441';r=results.get(rid)
    add(rid+'真实来源存在',r is not None,'不能用未检查冒充通过')
    if r:
        temporal=[u for u in r['rows'] if '之前接受其他媒体采访' in u.get('原文摘录','')]
        add('此前整改声称不变成当前实施事实',bool(temporal) and all(
            u.get('具体产品做法') and not prose_issues(u['原文摘录'],u['具体产品做法']) for u in temporal),
            '必须取得非空忠实转写；不能靠清空做法规避错误')
    return {'checks':checks,'errors':[c['check'] for c in checks if not c['passed']],
            'scope':'已实读来源的对象、口径和时间关系锚点，不是完整语义精确率/召回率'}


def main():
    p=argparse.ArgumentParser();p.add_argument('input',type=Path);p.add_argument('--output',type=Path,required=True)
    args=p.parse_args();report=inspect(json.loads(args.input.read_text(encoding='utf-8')))
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'checked':len(report['checks']),'errors':report['errors']},ensure_ascii=False))
    raise SystemExit(bool(report['errors']))


if __name__=='__main__':main()
