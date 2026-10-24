"""Real comment protocol/explicit-object regressions, not global accuracy."""
import argparse
import json
from pathlib import Path


def inspect(data):
    results={r['document']['record_id']:r for r in data.get('results',[])};checks=[]
    def add(name,passed,detail):checks.append({'check':name,'passed':bool(passed),'detail':detail})
    rid='T2-C-7963753211120747417';r=results.get(rid)
    add(rid+'真实来源存在',r is not None,'缺失来源不算通过')
    if r:
        rows=r.get('rows',[])
        add('明确短交通评论保持完整一行',len(rows)==1 and rows[0]['原始摘录']==r['document']['text'],
            '完整评论不改写、不拆分')
        summary=rows[0].get('观点摘要') if len(rows)==1 else None
        add('引用协议不得令有据短交通摘要消失',bool(summary)
            and all(w in summary for w in ('西四环','阜石路','四个红绿灯')),
            '真实原文明示两条路线均经过四个红绿灯；缺项目名不妨碍忠实转写。仍需原文对象关系核验，不能直接填入手写摘要')
    rid='T2-C-7963753211120747268';r=results.get(rid)
    add(rid+'真实来源存在',r is not None,'缺失来源不算通过')
    if r:
        rows=r.get('rows',[])
        add('驱鸟长评论保持完整一行',len(rows)==1 and rows[0]['原始摘录']==r['document']['text'],
            '有多个发言者和回复，也不拆为多行')
        names=rows[0].get('项目名称') if len(rows)==1 else None
        add('评论明示外部小区名称不被候选范围限制遗漏',isinstance(names,list)
            and any('郦城' in str(n) for n in names) and any('西冉金茂' in str(n) for n in names),
            '原文明确我在郦城、我们和西冉金茂在机场两侧；保留名称有据不代表把两侧都确认存在同样噪音。外部名称不编候选ID，不能硬归臻澐')
        add('外部项目数组保持位置对应',len(rows)==1 and all(isinstance(rows[0].get(k),list)
            for k in ('project_id','项目名称','项目角色')) and len({len(rows[0][k])
                for k in ('project_id','项目名称','项目角色')})==1,
            '候选外名称允许null ID，三个数组不得错位')
    return {'checks':checks,'errors':[c['check'] for c in checks if not c['passed']],
            'scope':'两条实读评论的协议及明确名称锚点，不是全样本金标准'}


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
