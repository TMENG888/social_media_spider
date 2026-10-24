"""Source-anchored observed defects, not an accuracy/recall estimate.

These checks inspect delivery rows, never rewrite them or choose boundaries.
Missing difficult sources fail rather than being replaced by easier examples.
"""
import argparse
import json
import re
from pathlib import Path


def inspect(data):
    results={r['document']['record_id']:r for r in data.get('results',[])}
    checks=[]
    def add(name,passed,detail):
        checks.append({'check':name,'passed':bool(passed),'detail':detail})
    def source(rid):
        result=results.get(rid)
        add(rid+'实际来源存在',result is not None,'固定困难来源缺失不算通过')
        return result
    r=source('T2-C-7963753211120747276')
    if r:
        rows=r.get('rows',[]);text=r['document']['text']
        summary=rows[0].get('观点摘要') or '' if len(rows)==1 else ''
        add('二选一比较保留未体验限定',len(rows)==1 and bool(summary)
            and bool(re.search(r'未听过|没听过|未体验|未亲历|没有听过',summary))
            and bool(re.search(r'二选一|相对|可能|也许|倾向',summary)),
            '同一发言轮先称没听过，再作二选一也许较好的比较；不能省略未体验成为确定听感')
        ids={t['标签路径ID'] for u in rows for t in u.get('标签明细',[])}
        anchors='住这就得少户外多宅家' in text and '驱鸟' in text
        add('避噪宅家建议不误标客户权益偏好',anchors and 'VOC-0565' not in ids,
            '实读该评论没有客户权益方案/居家权益服务偏好；仅为避噪生活建议，路径合法不等于定义匹配')
    for suffix in ('7268','7270','7272'):
        r=source('T2-C-796375321112074'+suffix)
        if r:
            rows=r.get('rows',[])
            add(suffix+'评论完整一行且摘要非空',len(rows)==1
                and rows[0].get('原始摘录')==r['document']['text']
                and bool(rows[0].get('观点摘要')),'不得以空摘要或拆回复回避多观点评论')
            if suffix=='7268' and len(rows)==1:
                summary=rows[0].get('观点摘要') or ''
                add('郦城录音与西冉问询不泛化两项目已证同受噪音',bool(summary)
                    and not bool(re.search(r'两(?:个)?(?:小区|项目).*均.*(?:噪音|驱鸟)',summary)),
                    '实读录音在郦城，西冉是问询和有分歧的回复，不得概括两项目均已证受扰；非空摘要是前提')
            if suffix=='7272' and len(rows)==1:
                summary=rows[0].get('观点摘要') or ''
                add('半壁店听感保留不影响生活程度',
                    '半壁店' in summary and bool(re.search(r'不影响生活|不至于影响生活|未影响生活',summary)),
                    '原文明示开窗可听见但不至于影响生活，户外声音大是另一场景；不可概括为严重影响生活')
    r=source('T2-2188228096999350274')
    if r:
        headings=['1. 开发品牌','2. 价格与门槛','3. 产品定位',
                  '4. 空间与户型','5. 精装与性能','6. 园林与会所']
        add('对比文章原文审阅锚点存在',all(h in r['document']['text'] for h in headings),
            '这些是实读原文明确的独立栏目，不是机器按关键词生成的生产边界')
        mixed=[]
        for row in r.get('rows',[]):
            quote=row.get('原始摘录') or row.get('原文摘录') or ''
            found=[h for h in headings if h in quote]
            if len(found)>1:mixed.append({'unit_id':row['unit_id'],'headings':found})
        add('明确不同比较栏目未再次合成大段',bool(r.get('rows')) and not mixed,
            {'observed_cross_topic_rows':mixed,'note':'单一户型细节可多标签；本检查只定位已观察的跨独立栏目合并，不证明全批粒度合格'})
    return {'checks':checks,'errors':[c['check'] for c in checks if not c['passed']],
            'scope':'5个固定实读来源的已观察精度缺陷；不是人工金标准精确率或召回率'}


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('input',type=Path)
    parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    if args.input.is_dir():
        data={'results':[json.loads(f.read_text(encoding='utf-8')) for f in args.input.glob('*.json')]}
    else:data=json.loads(args.input.read_text(encoding='utf-8'))
    report=inspect(data)
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'checked':len(report['checks']),'errors':report['errors']},ensure_ascii=False))
    raise SystemExit(bool(report['errors']))
