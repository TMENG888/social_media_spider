"""Observed full-source workmanship anchors, not automatic label grants."""
import argparse
import json
from pathlib import Path


def inspect(data):
    result=next((r for r in data.get('results',[])
                 if r['document']['record_id']=='T1-182247585093626012'),None)
    checks=[]
    def add(name,passed,detail):
        checks.append({'check':name,'passed':bool(passed),'detail':detail})
    add('真实工法口播来源存在',result is not None,'不以缺失来源或空结果冒充修复')
    if result:
        rows=result.get('rows',[])
        bathroom=[r for r in rows if '存水弯' in r.get('原文摘录','') and '50毫米' in r['原文摘录']]
        add('卫生间对象引导与紧接配置不被分离丢失',bool(bathroom) and any(
            '卫生间' in r['原文摘录'] for r in bathroom),
            '原文紧接问卫生间味道后回答两个防臭方案；对象引导与方案应同片，不能剔除对象引导后再以未明确卫生间拒绝配置')
        add('连续卫生间防臭方案与纠正问答不重复拆片',len(bathroom)==1
            and '自动补水' in bathroom[0]['原文摘录'] and '防臭芯' in bathroom[0]['原文摘录'],
            '实读完整原文：存水弯水封高度、自动补水及防臭芯纠正解释属同一连续完整方案；不是每个问答均须独立一片')
        add('明确地漏及共用存水弯配置不因缺品牌型号误拒',bool(bathroom) and any(
            t['标签路径ID']=='VOC-0294' for r in bathroom for t in r['标签明细']),
            '字典原文示例是品牌、型号、规格或配置，不要求兼有品牌型号；原文明示50毫米和共用存水弯，仍需正确对象和声称性质')
        kitchen=[r for r in rows if '耐高温密封胶' in r.get('原文摘录','')]
        add('后段明确烟道接口密封施工不漏质量标签',bool(kitchen) and any(
            t['标签路径ID']=='VOC-0478' for r in kitchen for t in r['标签明细']),
            '本来源后段明确专用耐高温密封胶的接口施工要求，不是仅列材料品牌；与前段高风压方案属不同事实，不按相同标签ID删除')
    return {'checks':checks,'errors':[c['check'] for c in checks if not c['passed']],
            'scope':'实读单一来源的连续主题和字典定义锚点，不是全样本金标准或精确率/召回率'}


def main():
    p=argparse.ArgumentParser();p.add_argument('input',type=Path)
    p.add_argument('--output',type=Path,required=True);args=p.parse_args()
    if args.input.is_dir():
        data={'results':[json.loads(f.read_text(encoding='utf-8')) for f in args.input.glob('*.json')]}
    else:data=json.loads(args.input.read_text(encoding='utf-8'))
    report=inspect(data)
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'checked':len(report['checks']),'errors':report['errors']},ensure_ascii=False))
    raise SystemExit(bool(report['errors']))


if __name__=='__main__':main()
