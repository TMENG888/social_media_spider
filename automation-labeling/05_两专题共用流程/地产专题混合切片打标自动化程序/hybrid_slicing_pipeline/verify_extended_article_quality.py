"""Additional independently read random-sample anchors, never production rules.

Only explicit observed facts are asserted. This packet is not an exhaustive
human gold standard and cannot establish global precision or recall.
"""
import argparse
import json
from pathlib import Path


def inspect(data):
    results={r['document']['record_id']:r for r in data.get('results',[])}
    checks=[]
    def add(name,passed,detail):checks.append({'check':name,'passed':bool(passed),'detail':detail})
    def source(rid):
        r=results.get(rid);add(rid+'实际固定来源存在',r is not None,'不能替换或跳过难例')
        return r
    exclusions={
        'T1-8000912876517501565':'校招岗位介绍，不是住宅产品具体配置',
        'T1-8000912876517501999':'中海上海个人实习经历，不是住宅产品具体配置',
        'T1-7194133258359930504':'所选唯一主体只有音轨账号信息，不能改用标题补成销售战绩',
        'T1-75177':'中海油服厨房招标，不是中海地产住宅产品',
        'T2-8000912876517502867':'酒店餐厅晚餐体验，不是研究住宅项目的餐厅配置或会所服务',
        'T2-75354':'医疗、音响和加油站消费司法案例，不是住宅项目口碑',
        'T2-75357':'养生馆诱导消费与调解报道，不是住宅项目物业服务或养老设施'}
    for rid,reason in exclusions.items():
        r=source(rid)
        if r:
            add(rid+'无关样本不强打住宅标签',r.get('complete') is True and not r.get('rows')
                and bool(r.get('excluded_intervals')),reason)
    r=source('T2-8000912876517503117')
    if r:
        ids={t['标签路径ID'] for u in r['rows'] for t in u['标签明细']}
        add('240平方米户型与4室2厅3卫明确事实不漏',{'VOC-0180','VOC-0186'}<=ids,
            '原文建面约240㎡、4室2厅3卫，有对应标准户型与建筑面积定义')
        add('家政套房不能继承全屋面积', 'VOC-0221' not in ids,
            '原文仅说明专属家政套房和独立服务动线，没有家政间面积或尺寸')
        add('同一240平方米户型设施不按每个标签拆行',any(
            '4室2厅3卫' in u.get('原始摘录','') and '专属家政套房' in u.get('原始摘录','') for u in r['rows']),
            '实读同一连续户型配置含格局、主卧及家政套房，不把每个设施当独立户型')
    r=source('T2-8000912876517503108')
    if r:
        ids={t['标签路径ID'] for u in r['rows'] for t in u['标签明细']}
        add('看房验资不误打客户预算',not ids.intersection({'VOC-0032','VOC-0033','VOC-0036','VOC-0037','VOC-0038'}),
            '原文是营销介绍的验资看房门槛，没有本人购房预算自述')
        add('明确323户不漏户数标签','VOC-0167' in ids,'原文总共323户是项目规模，不是批次供应')
    r=source('T2-8000912876517502797')
    if r:
        add('短探盘标题主体不编造设施',all(not u['标签明细'] for u in r.get('rows',[])),
            '原文只有春节探盘与臻澐名称，没有户型、园林、会所或个人需求等具体事实')
    return {'checks':checks,'errors':[x['check'] for x in checks if not x['passed']],
            'scope':'10篇已独立实读文章的对象、边界、定义和排除锚点；非完整标签金标准，不报告准确率'}


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('input',type=Path);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();report=inspect(json.loads(a.input.read_text(encoding='utf-8')))
    a.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'checked':len(report['checks']),'errors':report['errors']},ensure_ascii=False))
    raise SystemExit(bool(report['errors']))
