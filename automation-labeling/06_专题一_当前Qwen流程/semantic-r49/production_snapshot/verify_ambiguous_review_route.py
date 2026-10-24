"""Report branch ambiguities not reviewed independently; not proof of omission."""
import argparse
import json
from pathlib import Path


def diagnose(results):
    pending=[]
    for result in results:
        for audit in result.get('local_acceptance',[]):
            checked={c.get('choice_key') for c in (audit.get('independent_check') or {}).get('checks',[]) if isinstance(c,dict)}
            seen=set()
            for branch in audit.get('all_branch_audits',[]):
                for decision in (branch.get('response') or {}).get('decisions',[]):
                    if not isinstance(decision,dict):continue
                    key=decision.get('choice_key')
                    if decision.get('status')=='ambiguous' and key not in checked and key not in seen:
                        seen.add(key)
                        pending.append({'record_id':result['document']['record_id'],'case_id':audit['case_id'],
                            'choice_key':key,'branch_reason':decision.get('why'),
                            'question':'分支的不确定判断尚未经过独立定义核验；须区分真实证据不足和错误增加品牌/规格门槛，不能直接认定漏标。'})
    return pending


def main():
    parser=argparse.ArgumentParser();parser.add_argument('input',type=Path);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.input.is_dir():
        results=[json.loads(p.read_text(encoding='utf-8')) for p in (args.input/'documents').glob('*.json')]
    else:results=json.loads(args.input.read_text(encoding='utf-8'))['results']
    pending=diagnose(results)
    args.output.write_text(json.dumps({'sources':len(results),'unreviewed_ambiguities':pending,
        'note':'只读审计路由，不自动新增或删除标签，也不是全量金标准。'},ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'sources':len(results),'unreviewed_ambiguities':len(pending)},ensure_ascii=False))


if __name__=='__main__':main()
