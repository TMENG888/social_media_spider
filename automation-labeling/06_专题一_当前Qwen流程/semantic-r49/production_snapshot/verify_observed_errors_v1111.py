"""Independent source-derived acceptance anchors, not a global accuracy score.

These anchors were added after reading actual source text, not to relabel an
old negative gold set. They test known errors; other labels still need review.
"""
import argparse
import json
from pathlib import Path


def check(data):
    byid={r['document']['record_id']:r for r in data['results']}
    checks=[]
    examples=[
        ('T2-8000912876517503117',{'VOC-0186','VOC-0203'},
         {'VOC-0181','VOC-0184','VOC-0204','VOC-0211','VOC-0307','VOC-0309'},
         '建筑面积与客厅宽度有明示；不能从宽厅/LDKB、南向四面宽、主卫窗、衣帽间补房间朝向/主卧窗/衣柜'),
        ('T2-C-7963753211120747188',{'VOC-0029'},set(),
         '回复者明确说继续做等等党，是本人观望阶段；不据此判断购房时间、预算或项目'),
        ('T2-C-7963753211120747192',{'VOC-0066'},{'VOC-0061'},
         '体育场规划提问表达休闲配套信息关注，不自动表达地段位置关注'),
    ]
    for rid,required,forbidden,why in examples:
        r=byid.get(rid)
        if r is None:
            checks.append({'record_id':rid,'passed':False,'reason':'测试来源缺失'});continue
        tags={t['标签路径ID'] for row in r['rows'] for t in row['标签明细']}
        checks.append({'record_id':rid,'required':sorted(required),'forbidden':sorted(forbidden),
            'missing':sorted(required-tags),'wrong_extra':sorted(forbidden&tags),
            'passed':not(required-tags or forbidden&tags),'why':why,
            'source':r['document']['text'],
            'delivered':sorted(tags)})
    return {'checks':checks,'passed':all(c['passed'] for c in checks),
        'note':'三个已观察错误的独立锚点，不能证明其余事实零漏标零错标，也不是全面人工金标准。'}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('input',type=Path)
    parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    data=json.loads(args.input.read_text(encoding='utf-8'));report=check(data)
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'passed':report['passed'],'checks':[{k:v for k,v in c.items()
        if k in {'record_id','missing','wrong_extra','passed'}} for c in report['checks']]},ensure_ascii=False))
    if not report['passed']:raise SystemExit(1)


if __name__=='__main__':main()
