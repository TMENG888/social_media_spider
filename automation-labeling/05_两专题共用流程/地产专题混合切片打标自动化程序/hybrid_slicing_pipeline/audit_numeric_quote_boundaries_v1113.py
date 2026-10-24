"""Read-only quote diagnostics. Never rewrites numbers, boundaries or tags.

A substring can be literally present but cut a numerical token. Flag that
ambiguity for source review rather than silently assuming ASR punctuation.
"""
import argparse
import json
import re
from pathlib import Path


def numeric_boundary_hits(source, quote):
    if not quote:
        return []
    source = re.sub(r'\s+', '', source)
    quote = re.sub(r'\s+', '', quote)
    hits = []
    for match in re.finditer(re.escape(quote), source):
        start, end = match.span()
        left = start > 0 and quote[0].isdigit() and source[start-1].isdigit()
        right = end < len(source) and quote[-1].isdigit() and source[end].isdigit()
        if left or right:
            hits.append({'span': [start, end], 'cuts_left_number': left,
                         'cuts_right_number': right,
                         'source_context': source[max(0,start-18):min(len(source),end+18)]})
    return hits


def audit(results):
    flags = []
    for result in results:
        for row in result['rows']:
            source = row.get('原文摘录', row.get('原始摘录', ''))
            for line in str(row.get('打标说明', '')).splitlines():
                match = re.search(r'^(VOC-\d+).*?证据[:：](.*?)｜理由[:：](.*)$', line)
                if not match:
                    continue
                tag_id, quote, reason = match.groups()
                hits = numeric_boundary_hits(source, quote)
                if hits:
                    flags.append({'record_id': result['document']['record_id'],
                                  'unit_id': row['unit_id'], 'tag_id': tag_id,
                                  'quote': quote, 'reason': reason, 'hits': hits,
                                  'action': '核对完整数字与分隔位置，不猜测正确数值；不是自动删标依据'})
    return {'sources': len(results), 'numeric_boundary_flags': flags,
            'note': '只检查已输出说明中的引文数字边界；零线索不代表所有数值解释正确。'}


def main():
    p = argparse.ArgumentParser()
    p.add_argument('input', type=Path)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    data = json.loads(args.input.read_text(encoding='utf-8'))
    report = audit(data['results'])
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'sources': report['sources'],
                      'numeric_boundary_flags': len(report['numeric_boundary_flags'])}))


if __name__ == '__main__':
    main()
