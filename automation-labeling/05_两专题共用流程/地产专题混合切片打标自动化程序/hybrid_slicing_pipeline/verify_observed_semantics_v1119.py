"""Read-only anchors from actual newly inspected sources, not accuracy scores.

No labels or summaries are rewritten here. A missing source is not a pass.
These known-error checks supplement, not replace, all-source semantic review.
"""
import argparse
import json
from pathlib import Path


def check(data):
    byid = {r['document']['record_id']: r for r in data['results']}
    checks = []

    def add(rid, requirement, predicate):
        result = byid.get(rid)
        checks.append({'record_id': rid, 'requirement': requirement,
            'passed': bool(result and result.get('complete') and predicate(result)),
            'source_present': result is not None})

    add('T2-8000912876517503108',
        '750米只对应五路居地铁站，不扩为西四环距离',
        lambda r: all('西四环及地铁' not in (row.get('观点摘要') or '')
                      for row in r['rows']))
    add('T1-316877139627506490',
        '识别不清的ASR材料不在做法中确定为竹桃楠材料',
        lambda r: all('竹桃楠等环保材料' not in (row.get('具体产品做法') or '')
                      for row in r['rows']))
    add('T1-182247585093626012',
        '纯参观邀约及视频结尾没有产品配置事实，不作为产品单元',
        lambda r: all(not (row.get('原文摘录') or '').startswith('3号院海师傅带着大家看工法样板间')
                      for row in r['rows']))
    add('T1-182247585093626012',
        '烟道止逆与后续耐高温密封分别有事实，同为工艺质量也不能误删',
        lambda r: len([row for row in r['rows'] if any(t['标签路径ID'] == 'VOC-0478'
                      for t in row['标签明细'])]) >= 2)
    add('T2-C-7963753211120747417',
        '交通是短板为明确评价，保留客户交通关注且评论完整一行',
        lambda r: len(r['rows']) == 1
            and r['rows'][0]['原始摘录'] == r['document']['text']
            and any(t['标签路径ID'] == 'VOC-0062' for t in r['rows'][0]['标签明细']))
    add('T2-8000912876517503117',
        '南向四面宽不得擅自分配客厅和主卧朝向',
        lambda r: not {'VOC-0204', 'VOC-0211'} & {t['标签路径ID']
                      for row in r['rows'] for t in row['标签明细']})
    return {'checks': checks, 'passed': all(c['passed'] for c in checks),
        'note': '六项实际来源锚点；不代表全量精确率/召回率，不证明其余切片或标签全部正确。'}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('input', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = check(json.loads(args.input.read_text(encoding='utf-8')))
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False))
    if not report['passed']:raise SystemExit(1)


if __name__ == '__main__':main()
