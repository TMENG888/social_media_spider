"""Evidence-specific regression checks; never a population accuracy claim."""
import argparse
import json
from pathlib import Path
import delivery_v8 as v
import evaluate_delivery_v6 as old

ADDITIONAL=[
    ('T1-4279014799868510031','VOC-0165',False,'','主体ASR没有容积率；标题不能标到主体摘录'),
    ('T1-4279014799868510031','VOC-0186',False,'','主体ASR没有建筑面积；标题不能当本片事实'),
    ('T2-C-7963753211120747367','VOC-0062',True,'','评论本人明确表达交通拥堵关注'),
    ('T2-C-7963753211120747367','VOC-0144',True,'','评论明确说西四环、红绿灯及上主路情况'),
    ('T2-C-7963753211120747367','VOC-0169',False,'','评论没有说洋房；不能从父文章继承配置'),
    ('T2-C-7963753211120747367','VOC-0384',False,'','评论没有说泳池；父文章设施不能冒充评论事实'),
    ('T1-1206064897007145818','VOC-0195',False,'','空间扩容200%不是明确层高'),
    ('T1-1206064897007145818','VOC-0380',False,'','别墅套内露台茶室不是社区会所茶室'),
    ('T1-2651643050694719236','VOC-0203',True,'8.5米','建面167㎡与宽厅8.5米同句，不能整句误删房间尺寸'),
    ('T1-3030118674814531486','VOC-0186',True,'建筑面积：190㎡','190㎡独立户型应各自有面积标签'),
    ('T1-3030118674814531486','VOC-0186',True,'建筑面积：225㎡','225㎡独立户型不能因190㎡已标而漏标'),
    ('T1-3030118674814531486','VOC-0186',True,'建筑面积：245㎡','245㎡独立户型不能只在文章层面查是否存在标签'),
    ('T1-3030118674814531486','VOC-0186',True,'建筑面积：278㎡','278㎡户型与次卧介绍保持连续并有面积标签'),
    ('T1-3030118674814531486','VOC-0186',True,'建筑面积：281㎡','281㎡独立户型的面积事实不能漏标'),
    ('T1-3030118674814531486','VOC-0213',True,'建筑面积：190㎡','190㎡主卧大套间应核查主卧布局'),
    ('T1-3030118674814531486','VOC-0213',True,'建筑面积：281㎡','281㎡主卧酒店行政套房应独立核查主卧布局'),
    ('T1-8000912876517502279','VOC-0186',True,'99-158㎡','面积标签必须落到带实际面积值的切片'),
    ('T1-3030118674814531486','VOC-0192',False,'建筑面积：225㎡','南北双阳台没有明确通透/通风事实，不能推导户型通风'),
    ('T1-3030118674814531486','VOC-0418',False,'18万方购物中心','一路之隔的外部商场不是住宅公区的社区商业超市'),
    ('T1-3030118674814531486','VOC-0419',False,'18万方购物中心','外部商场餐饮不能标成住宅公区社区商业餐饮'),
    ('T2-8000912876517502735','VOC-0563',False,'','营销描绘社交机会与会所设施不证明实际业主权益运营内容'),
    ('T1-3030118674814531486','VOC-0208',True,'建筑面积：190㎡','3+1房2厅2卫明确卫生间数量2，不能因对象简称误删'),
    ('T1-3030118674814531486','VOC-0208',True,'建筑面积：225㎡','225㎡户型3卫应单独标数量'),
    ('T1-3030118674814531486','VOC-0208',True,'建筑面积：245㎡','245㎡户型3卫不能因其他户型已标而漏标'),
    ('T1-3030118674814531486','VOC-0208',True,'建筑面积：278㎡','278㎡户型4卫应独立落标签'),
    ('T1-3030118674814531486','VOC-0208',True,'建筑面积：281㎡','281㎡户型4卫与其他配置同片保留'),
]


def tags(result,contains=''):
    rows=result['rows']
    if contains:rows=[u for u in rows if contains in str(u.get('原文摘录',u.get('原始摘录','')))]
    return {t['标签路径ID'] for u in rows for t in u['标签明细']}


def main():
    p=argparse.ArgumentParser();p.add_argument('--result',type=Path,required=True)
    p.add_argument('--baseline',type=Path,default=Path(__file__).parent/'test_results_v51_20261009_api/delivery_results.json')
    args=p.parse_args();data=json.loads(args.result.read_text(encoding='utf-8'));before=json.loads(args.baseline.read_text(encoding='utf-8'))
    checks=old.compare(before,data);new={r['document']['record_id']:r for r in data['results']};previous={r['document']['record_id']:r for r in before['results']}
    for rid,tid,positive,contains,why in ADDITIONAL:
        if rid not in new:continue
        present=tid in tags(new[rid],contains)
        checks.append({'record_id':rid,'标签路径ID':tid,'锚点性质':'positive' if positive else 'negative',
            '旧版是否标出':tid in tags(previous[rid],contains) if rid in previous else None,
            '新版是否标出':present,'锚点通过':present==positive,'限定证据':contains,'独立检查理由':why})
    comparison=[]
    for rid,result in new.items():
        oldtags=tags(previous[rid]) if rid in previous else set();newtags=tags(result)
        deferred=(result.get('reviewed') or {}).get('deferred_evidence') or []
        comparison.append({'record_id':rid,'专题':result['document']['topic'],'平台':result['document']['row'].get('平台'),
            '来源类型':result['document']['kind'],'旧版单元数':len(previous[rid]['rows']) if rid in previous else None,
            '新版单元数':len(result['rows']),'旧版标签种数':len(oldtags),'新版标签种数':len(newtags),
            '新增标签':sorted(newtags-oldtags),'移除标签':sorted(oldtags-newtags),'证据歧义待审标签':[{'编号':a['choice_key'],'原因':a['reason']} for a in deferred],
            '来源处理完整':result['complete']})
    data['tables']['已知问题锚点对比']=checks;data['schemas']['已知问题锚点对比']=list(dict.fromkeys(k for r in checks for k in r))
    data['tables']['逐来源版本对比']=comparison;data['schemas']['逐来源版本对比']=list(comparison[0])
    data['summary']['evidence_anchor_checks']=len(checks);data['summary']['evidence_anchor_passed']=sum(r['锚点通过'] for r in checks)
    for name in ['已知问题锚点对比','逐来源版本对比']:v.base.write_csv(args.result.parent/(name+'.csv'),data['tables'][name],data['schemas'][name])
    v.base.save_json(args.result,data)
    print(v.base.dumps({'checks':len(checks),'passed':sum(r['锚点通过'] for r in checks),'failed':[r for r in checks if not r['锚点通过']]}),flush=True)
    if any(not r['锚点通过'] for r in checks):raise SystemExit(1)


if __name__=='__main__':main()
