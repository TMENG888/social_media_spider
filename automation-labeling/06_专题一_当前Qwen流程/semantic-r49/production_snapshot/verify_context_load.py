"""Context/granularity diagnostics, never a keyword or size slicing rule."""
import argparse
import json
import statistics
from collections import Counter
from pathlib import Path


def profile(results,calls):
    slices=[]
    for result in results:
        doc=result['document']
        for row in result['rows']:
            quote=row.get('原文摘录',row.get('原始摘录',''))
            slices.append({'record_id':doc['record_id'],'unit_id':row['unit_id'],'来源类型':doc['kind'],
                '字符数':len(quote),'标签数':len(row['标签明细']),
                '提醒':'需按对象与主题复核，不能仅凭长度/标签数量认定粒度错误'})
    phases={}
    for phase in sorted({c['phase'] for c in calls}):
        selected=[c for c in calls if c['phase']==phase]
        known=[c['prompt_tokens'] for c in selected if c.get('prompt_tokens') is not None]
        phases[phase]={'逻辑请求数':len(selected),'缓存读取数':sum(bool(c.get('cache_hit')) for c in selected),
            '本次新请求数':sum(not c.get('cache_hit') for c in selected),'未知输入Token请求数':len(selected)-len(known),
            '输入Token中位数':statistics.median(known) if known else None,
            '最大输入Token':max(known) if known else None,
            '状态':dict(Counter(c['status'] for c in selected))}
    return {'slices':sorted(slices,key=lambda s:s['字符数'],reverse=True),'phases':phases,
        'note':'输入负载与语义粒度为独立诊断，不等于准确率；完整适用字典必须仍全部核对，不按候选限制标签。'}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('input',type=Path);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();data=json.loads(args.input.read_text(encoding='utf-8'))
    report=profile(data['results'],data['calls'])
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'sources':len(data['results']),'slices':len(report['slices']),
        'largest_slices':report['slices'][:3]},ensure_ascii=False))


if __name__=='__main__':main()
