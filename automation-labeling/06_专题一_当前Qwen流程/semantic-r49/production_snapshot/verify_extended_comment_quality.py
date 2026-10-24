"""Independently read comment anchors. Not production rules or gold metrics."""
import argparse
import json
import re
from pathlib import Path


def inspect(data):
    results={r['document']['record_id']:r for r in data.get('results',[])};checks=[]
    def add(name,ok,detail):checks.append({'check':name,'passed':bool(ok),'detail':detail})
    def row(suffix):
        rid='T2-C-796375321112074'+suffix;r=results.get(rid)
        add(rid+'来源存在',r is not None,'固定来源缺失不能跳过')
        if not r:return None
        rows=r.get('rows',[])
        add(suffix+'完整评论单行有摘要',len(rows)==1 and rows[0].get('原始摘录')==r['document']['text']
            and bool(rows[0].get('观点摘要')),'不拆父子回复、不空摘要规避事实核验')
        return rows[0] if len(rows)==1 else None
    u=row('7277')
    if u:
        add('视频补充不无据推断声音或负向体验','VOC-0157' not in {t['标签路径ID'] for t in u['标签明细']}
            and not re.search(r'吵|轰鸣|噪音|噪声|扰民',u.get('观点摘要') or ''),
            '仅说再补西冉大飞机[视频]10s，本测试没有视频内容，不借父文章填成听感')
    u=row('7283')
    if u:
        add('泛指问题不大不借父文硬填机场噪音','VOC-0157' not in {t['标签路径ID'] for t in u['标签明细']}
            and not re.search(r'噪音|噪声|机场|驱鸟',u.get('观点摘要') or ''),
            '本条仅说还好问题不大；父文定位可保留审计，但不能冒充本条明确评价对象')
    u=row('7285')
    if u:
        summary=u.get('观点摘要') or ''
        add('玉海园室外可闻与室内听不见均保留','玉海园' in summary
            and bool(re.search(r'外(?:边|面)|室外|户外',summary))
            and bool(re.search(r'家里|室内|家中',summary)) and bool(re.search(r'听不(?:到|见)|听不到|未听到|无(?:飞机)?声',summary)),
            '原文明示居住四年，外面听到、家里听不到，不能概括完全无噪音')
    u=row('7282')
    if u:
        add('永引南路等级更正保留', '主干路' in (u.get('观点摘要') or '')
            and not re.search(r'永引南路(?:为|是)快速路',u.get('观点摘要') or ''),
            '父评明确城市主干路，回复认可，不能沿用父文快速路说法')
    u=row('7185')
    if u:
        summary=u.get('观点摘要') or ''
        add('地铁位置事实不漏标签','VOC-0142' in {t['标签路径ID'] for t in u['标签明细']},
            '原文问西冉地铁规划并回复最近四季青两公里，明确交通对象和距离')
        add('暂时无规划不写已规划地铁',bool(re.search(r'暂无|暂时没有|没有规划|无地铁规划|未规划',summary)),
            '回复者说据了解暂时没有规划，不应写成官方永远不会建，也不应写已规划')
    u=row('7186')
    if u:
        add('四口之家不推断人口增加购房动机','VOC-0053' not in {t['标签路径ID'] for t in u['标签明细']},
            '两车四人属于当前自述，不含家庭人口增加或因此购房的事实')
    u=row('7192')
    if u:
        add('体育场规划问询不变为已建事实',bool(re.search(r'询问|问|想了解|想知道',u.get('观点摘要') or '')),
            '原文询问是否掌握体育场规划，不能断言设施已建成或已运营')
    return {'checks':checks,'errors':[c['check'] for c in checks if not c['passed']],
            'scope':'7条实读评论的限定、对象、定义及漏标锚点，非全面金标准精确率/召回率'}


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('input',type=Path);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();report=inspect(json.loads(a.input.read_text(encoding='utf-8')))
    a.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'checked':len(report['checks']),'errors':report['errors']},ensure_ascii=False))
    raise SystemExit(bool(report['errors']))
