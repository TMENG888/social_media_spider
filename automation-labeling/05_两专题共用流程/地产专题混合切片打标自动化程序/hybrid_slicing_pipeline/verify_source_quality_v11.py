"""Read-only source/result review packet, not an accuracy or deletion gate.

All repeated-label pairs remain visible, including legitimate distinct facts.
Copy diagnostics also check long subclauses, not only whole-excerpt equality.
"""
import argparse
import json
import re
from collections import defaultdict
from difflib import SequenceMatcher
from pathlib import Path


def compact(value):
    return re.sub(r'[\s\W_]+', '', value or '', flags=re.UNICODE)


def copy_profile(source, prose):
    a, b = compact(source), compact(prose)
    if not b:
        return {'missing': True, 'longest_copy': 0, 'prose_copy_share': None,
                'needs_review': True}
    match = SequenceMatcher(None, a, b, autojunk=False).find_longest_match()
    share = match.size / len(b)
    return {'missing': False, 'longest_copy': match.size,
            'prose_copy_share': round(share, 4),
            'needs_review': match.size >= 25 and share >= .8}


def review_packet(results):
    sources = []
    flags = []
    pairs = []
    for result in results:
        doc = result['document']
        by_tag = defaultdict(list)
        source_rows = []
        for row in result['rows']:
            quote = row.get('原文摘录', row.get('原始摘录', ''))
            prose = row.get('具体产品做法', row.get('观点摘要'))
            profile = copy_profile(quote, prose)
            source_rows.append({'unit_id': row['unit_id'], '摘录': quote,
                '转写或摘要': prose, '标签': row['标签明细'],
                '验收状态': row['验收状态'], '备注': row['备注'],
                'copy_profile': profile})
            if profile['needs_review'] and (doc['topic']=='全国地产设计产品力监测' or profile['missing'] or len(quote)>40):
                flags.append({'record_id': doc['record_id'], 'unit_id': row['unit_id'],
                    'reason': '转写/摘要缺失或长子句近似照搬，须原文复核', 'profile': profile})
            for tag in row['标签明细']:
                by_tag[tag['标签路径ID']].append(row)
        for tag, rows in by_tag.items():
            for i, left in enumerate(rows):
                for right in rows[i+1:]:
                    pairs.append({'record_id': doc['record_id'], '标签路径ID': tag,
                        'unit_a': left['unit_id'], 'unit_b': right['unit_id'],
                        'quote_a': left.get('原文摘录', left.get('原始摘录')),
                        'quote_b': right.get('原文摘录', right.get('原始摘录')),
                        'review_question': '是否同一对象同一事实的综述/细节重述？不同项目/户型/态度应保留，不按标签ID删除。'})
        sources.append({'record_id': doc['record_id'], '来源类型': doc['kind'],
            'complete': result.get('complete'), '完整原文': doc['text'],
            'rows': source_rows, 'excluded_intervals': result.get('excluded_intervals', []),
            'duplicate_fact_audit': result.get('duplicate_fact_audit', [])})
    return {'sources': sources, 'copy_flags': flags, 'same_tag_pairs': pairs,
        'note': '复制诊断与相同标签是复核线索，不直接证明误标/漏标；必须逐项对照原文和字典定义。'}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('input', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.input.is_dir():
        data={'results':[json.loads(path.read_text(encoding='utf-8')) for path in sorted((args.input/'documents').glob('*.json'))]}
    else:
        data = json.loads(args.input.read_text(encoding='utf-8'))
    report = review_packet(data['results'])
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'sources': len(report['sources']), 'copy_flags': len(report['copy_flags']),
        'same_tag_pairs': len(report['same_tag_pairs'])}, ensure_ascii=False))


if __name__ == '__main__':
    main()
