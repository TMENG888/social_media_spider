"""Same-batch deltas and explicit regressions, not invented precision/recall."""
import argparse
import json
from collections import Counter
from pathlib import Path


def assess(prior,current):
    old={u['unit_id']:u for r in prior['results'] for u in r['rows']}
    new={u['unit_id']:u for r in current['results'] for u in r['rows']}
    delta=[]
    for r in current['results']:
        traces={t['unit_id']:t for t in r['traces']}
        for u in r['rows']:
            before={t['标签路径ID'] for t in old.get(u['unit_id'],{}).get('标签明细',[])}
            for tag in u['标签明细']:
                if tag['标签路径ID'] not in before:
                    proof=next((x for x in traces[u['unit_id']].get('全字典补选证据',traces[u['unit_id']].get('标签证据与归属',[])) if x['key']=='D'+tag['标签路径ID'][4:]),None)
                    delta.append({'unit_id':u['unit_id'],'来源类型':r['document']['kind'],'标签路径ID':tag['标签路径ID'],
                        '标签强调方向':tag['标签强调方向'],'原文':u.get('原文摘录',u.get('原始摘录')),
                        '核验依据':proof,'处理':'原单元补标签' if u['unit_id'] in old else '恢复原范围单元及标签'})
    def tags(uid):return {t['标签路径ID'] for t in new.get(uid,{}).get('标签明细',[])}
    checks=[{'检查项':'体育公园不能标会所泳池','unit_id':'T1-879334445254348759-M001',
        '通过':'VOC-0384' not in tags('T1-879334445254348759-M001')},
        {'检查项':'预估户型面积不能编成赠送面积','unit_id':'T1-2651643050694719236-M008',
        '通过':'VOC-0188' not in tags('T1-2651643050694719236-M008')},
        {'检查项':'所有有效评论完整一行','通过':all(not r['rows'] or len(r['rows'])==1 and r['rows'][0]['原始摘录']==r['document']['text'] for r in current['results'] if r['document']['kind']=='评论')},
        {'检查项':'所有片内标签ID唯一','通过':all(len(u['标签明细'])==len({t['标签路径ID'] for t in u['标签明细']}) for u in new.values())},
        {'检查项':'不漏来源记录','通过':{r['document']['record_id'] for r in current['results']}=={r['document']['record_id'] for r in prior['results']}}]
    def added_tags(uid):return tags(uid)-{t['标签路径ID'] for t in old.get(uid,{}).get('标签明细',[])}
    forbidden=[('项目数不能补成楼栋数','T1-75303-M009','VOC-0166'),
        ('泳池材质不能补成大门材质','T1-75218-M013','VOC-0333'),
        ('庭院串联不能补成风雨连廊','T2-1263114957749348749-V008','VOC-0414'),
        ('项目案名不能补成户型名','T2-8000912876517502886-V001','VOC-0179'),
        ('双国企不能补成央企','T2-75373-V002','VOC-0092'),
        ('购房折扣不能补成装标','T2-75368-V001','VOC-0492'),
        ('营销医疗配套不能补成本人关注','T2-8000912876517503087-V001','VOC-0064'),
        ('主卧面积不能默认主卧数量1','T1-1430793182877171531-M015','VOC-0210')]
    checks += [{'检查项':name,'unit_id':uid,'通过':tid not in added_tags(uid)} for name,uid,tid in forbidden]
    measures=[]
    version=current.get('summary',{}).get('version','');joint=version.startswith('v95-');keyword=version.startswith(('v94-','v95-'));single=version.startswith(('v93-','v94-','v95-'))
    for name,pack in [('上轮原文关键词补标基线' if joint else '上轮单片分组交付基线' if keyword else 'v92全字典补选基线' if single else 'v91基线',prior),('切片与已有标签联合补标' if joint else '单片分组加关键词兜底' if keyword else 'v93单片分组查漏' if single else 'v92全字典补选',current)]:
        rows=[u for r in pack['results'] for u in r['rows']]
        measures.append({'版本':name,'产品单元数':sum('具体产品做法' in u for u in rows),
            '文章观点数':sum(u.get('来源类型')=='文章' for u in rows),'评论观点数':sum(u.get('来源类型')=='评论' for u in rows),
            '标签数':sum(len(u['标签明细']) for u in rows),
            '无标签或理由文案为空数':sum(not u['标签明细'] or not u['打标说明'] or not u.get('具体产品做法',u.get('观点摘要')) for u in rows),
            '待核单元数':sum(len(r.get('pending_units',[])) for r in pack['results'])})
    return {'same_batch':True,'sources':len(current['results']),'measures':measures,
        'supplement_status':current['supplement_status'],'regression_checks':checks,'new_label_details':delta,
        'limitations':'已知案例回归和字段/来源完整性测试；没有独立人工全量金标准，不报告总体漏标率、精确率或零漏标。'}


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--prior',type=Path,required=True);ap.add_argument('--output-dir',type=Path,required=True);a=ap.parse_args()
    prior=json.loads(a.prior.read_text(encoding='utf-8'));current=json.loads((a.output_dir/'delivery_results.json').read_text(encoding='utf-8'))
    report=assess(prior,current);assert all(x['通过'] for x in report['regression_checks'])
    (a.output_dir/'supplement_quality_evaluation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='new_label_details'},ensure_ascii=False))


if __name__=='__main__':main()
