"""Source-first acceptance anchors. Not a proxy for exhaustive human gold labels.

Anchors are fixed from independently read source facts, not output candidates.
Diagnostic only: never erase a rejected source or rewrite production results.
"""
import argparse
import json
from collections import Counter
from pathlib import Path
import delivery_v8 as p

# Explicit, applicable facts only. Presence in the dictionary alone is not
# proof of semantic support. Ambiguous ASR/units and out-of-topic paths omitted.
POSITIVE = [
    ('T1-5886432952923525120','VOC-0186','104-148'),
    ('T1-7868135928622720541','VOC-0165','2.3'),
    ('T1-7868135928622720541','VOC-0345','一梯一户'),
    ('T1-7868135928622720541','VOC-0206','双阳台'),
    ('T1-7868135928622720541','VOC-0380','茶室'),
    ('T1-7868135928622720541','VOC-0378','瑜伽室'),
    ('T1-2944395937563134382','VOC-0165','1.6'),
    ('T1-8000912876517502274','VOC-0186','210-370'),
    ('T2-2188228096999350274','VOC-0186','139'),
    ('T2-2188228096999350274','VOC-0189','80%'),
    ('T2-8000912876517503108','VOC-0165','1.43'),
    ('T2-8000912876517503108','VOC-0189','90%'),
    ('T2-8000912876517503117','VOC-0186','240'),
    ('T2-8000912876517503117','VOC-0208','3卫'),
    ('T2-8000912876517502998','VOC-0157','噪音'),
    # Whole-comment anchors read independently of model candidates.
    ('T2-C-7963753211120747417','VOC-0144','四个红绿灯'),
    ('T2-C-7963753211120747269','VOC-0157','噪音时长'),
    ('T2-C-7963753211120747271','VOC-0157','车流声'),
    ('T2-C-7963753211120747272','VOC-0157','飞机声音'),
    ('T2-C-7963753211120747273','VOC-0157','马路噪声'),
    ('T2-C-7963753211120747275','VOC-0144','双向6车道限速80'),
    ('T2-C-7963753211120747279','VOC-0157','噪音总体差不多'),
    ('T2-C-7963753211120747285','VOC-0157','飞机的声音'),
    ('T2-C-7963753211120747185','VOC-0142','四季青地铁有两公里'),
    ('T2-C-7963753211120747186','VOC-0005','我家里两辆车但是家里有四个人'),
    ('T2-C-7963753211120747187','VOC-0157','飞机噪音影响太大'),
]
IRRELEVANT = {
    'T1-8000912876517501565':'中国建筑国际招聘，不是住宅配置',
    'T1-8000912876517501999':'实习招聘，不是住宅配置',
    'T1-7194133258359930504':'选用主体只有音乐署名，不以标题补正文',
    'T1-75177':'中海油服工业采购，不是中海地产住宅',
    'T2-75354':'医疗、电商及加油站消费案例，与住宅专题无关',
    'T2-75357':'养生馆消费纠纷，与住宅专题无关',
    'T2-8000912876517502867':'璞瑄酒店餐厅，不是候选住宅项目',
    'T2-C-1238450':'父文酒店餐厅消费，不能标为住宅购买需求',
    'T2-C-1238236':'仅交流群推广，没有住宅配置或客户事实',
}

# Retain the historical anchor for audit, but do not demand a guessed number.
# This correction follows inspection of the raw source, not output success.
AMBIGUOUS_ANCHORS = {
    ('T2-8000912876517503108','VOC-0165','1.43'):
        '原文“容积率仅1.433-5层”数字黏连，无法明确划分容积率与楼层；禁止猜1.43',
}


def inspect(results, documents, taxonomy):
    byid={r['document']['record_id']:r for r in results}
    anchors=[]
    for rid,tid,quote in POSITIVE:
        doc=next((d for d in documents if d['record_id']==rid),None)
        result=byid.get(rid)
        if doc is None:
            state='不在当前执行子集，未评估'
        elif (rid,tid,quote) in AMBIGUOUS_ANCHORS:
            state='源证据歧义，保留复核，不计作应打或漏标'
        elif quote not in doc['text']:
            state='源证据锚点未通过，不能计入标签效果'
        elif result is None: state='来源尚未完成'
        elif any(any(t['标签路径ID']==tid for t in row['标签明细'])
                 and quote in row.get('原文摘录',row.get('原始摘录','')) for row in result['rows']):
            state='通过'
        else: state='有据标签未在交付行落地，需定位'
        anchors.append({'record_id':rid,'tag_id':tid,'原文锚点':quote,'结果':state,
            '源证据限制':AMBIGUOUS_ANCHORS.get((rid,tid,quote))})
    negatives=[{'record_id':rid,'依据':why,'结果':'通过' if rid in byid and not byid[rid]['rows']
                else '来源尚未完成' if rid not in byid else '误纳入专题，需定位'} for rid,why in IRRELEVANT.items()]
    errors=[];repeat=[];comments=[];long=[]
    for r in results:
        d=r['document'];ids=[]
        catalogue=p.v.registry(taxonomy,d['topic'])
        actual={t['tag_id']:t for t in catalogue.values()}
        if d['kind']=='评论':
            ok=len(r['rows'])<=1 and all(row['原始摘录']==d['text'] for row in r['rows'])
            comments.append({'record_id':d['record_id'],'完整评论且最多一行':ok,
                             '输出行数':len(r['rows']),'无行需检查排除依据':not r['rows']})
            if not ok: errors.append({'record_id':d['record_id'],'错误':'评论被切分或原文被改写'})
        for row in r['rows']:
            text=row.get('原文摘录',row.get('原始摘录',''))
            if d['kind']=='文章' and len(text)>600:
                long.append({'record_id':d['record_id'],'unit_id':row['unit_id'],'字符数':len(text),
                             '状态':'语义粒度待复核；长度不直接决定切片边界'})
            per=[]
            for tag in row['标签明细']:
                tid=tag['标签路径ID'];ids.append(tid);per.append(tid)
                if tid not in actual:errors.append({'unit_id':row['unit_id'],'非法或不适用标签':tid})
                if set(tag)!={'标签路径ID','标签编号','一级标签','二级标签','三级标签','四级标签','五级标签','标签强调方向'}:
                    errors.append({'unit_id':row['unit_id'],'错误':'标签JSON不满足八键合同'})
            if len(per)!=len(set(per)):errors.append({'unit_id':row['unit_id'],'错误':'同片标签重复'})
        for tid,n in Counter(ids).items():
            if n>1:repeat.append({'record_id':d['record_id'],'标签':tid,'出现次数':n,
                '状态':'待比较对象及事实，不能只按相同标签ID去重'})
    return {'summary':{'planned_sources':len(documents),'saved_sources':len(results),
             'completed_sources':sum(bool(r['complete']) for r in results),
             'positive_anchors':dict(Counter(a['结果'] for a in anchors)),
             'irrelevant_sources':dict(Counter(a['结果'] for a in negatives)),
             'contract_errors':len(errors),'long_article_slices':len(long),'repeated_tag_groups':len(repeat),
             'note':'独立证据锚点诊断，不是全标签金标准；未通过时不能宣称不漏标不误标。'},
            'anchors':anchors,'negative_cases':negatives,'errors':errors,
            'comment_integrity':comments,'granularity_review':long,'repeated_tag_review':repeat}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--folder',type=Path,required=True)
    parser.add_argument('--input',type=Path);parser.add_argument('--sample',type=Path);args=parser.parse_args()
    sample=json.loads((args.sample or args.folder/'fresh_sample.json').read_text(encoding='utf-8'))
    data=args.input or args.folder/'delivery_results.json'
    # Never combine checkpoints with different code/taxonomy signatures.
    results=json.loads(data.read_text(encoding='utf-8'))['results']
    report=inspect(results,sample['documents'],p.base.load_taxonomy(p.v.legacy.TAXONOMY))
    p.base.save_json(args.folder/'independent_evidence_audit.json',report)
    print(p.base.dumps(report['summary']))


if __name__=='__main__':main()
