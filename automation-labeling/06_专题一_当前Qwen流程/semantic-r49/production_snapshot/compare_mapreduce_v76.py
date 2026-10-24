"""Same-source, independent limited evidence anchors. No global accuracy claim."""
import argparse
import json
from pathlib import Path
from evaluate_independent_label_anchors_v59 import evaluate

EXTRA = [
    {'record_id': 'T1-5886432952923525120', 'quote': '建面约104-148㎡3-4房',
     'required': ['VOC-0186'], 'forbidden': [], 'basis': '住宅建筑面积明示，定义不要求编号及完整房厅结构。'},
    {'record_id': 'T2-8000912876517503108', 'quote': '央企准现房27年年底交房',
     'required': [], 'forbidden': ['VOC-0102'], 'basis': '未来交付计划不是已发生的准时交付业绩。'},
    {'record_id': 'T2-7055232109415196221', 'quote': '3.3米层高',
     'required': ['VOC-0195'], 'forbidden': ['VOC-0126'], 'basis': '该房源户型层高不是地块规划条件层高。'},
    {'record_id': 'T2-7055232109415196221', 'quote': '法式装修风格',
     'required': ['VOC-0229'], 'forbidden': [], 'review_only': ['VOC-0230'],
     'basis': '只明确整体装修风格，没有具体色彩描述；0230示例有风格交叉，需业务澄清。'}
]

def stats(data):
    rows = [row for result in data['results'] for row in result['rows']]
    return {'processed_sources': len(data['results']),
        'incomplete_sources': sum(not r['complete'] for r in data['results']),
        'product_units': sum('content_id' in r for r in rows),
        'article_opinion_units': sum(r.get('来源类型') == '文章' for r in rows),
        'comment_opinion_units': sum(r.get('来源类型') == '评论' for r in rows),
        'tag_associations': sum(len(r['标签明细']) for r in rows),
        'empty_tag_units': sum(not r['标签明细'] for r in rows),
        'empty_prose_units': sum(not r.get('具体产品做法', r.get('观点摘要')) for r in rows),
        'automatic_pass': sum(r['验收状态'] == '自动通过' for r in rows)}

def compare(before, after, reference):
    ids = {r['document']['record_id'] for r in after['results']}
    before_subset = dict(before, results=[r for r in before['results'] if r['document']['record_id'] in ids])
    reference = dict(reference, anchors=reference['anchors'] + EXTRA)
    reports = [evaluate(d, reference) for d in (before_subset, after)]
    changes = []
    map_hits = 0
    after_records = {r['document']['record_id']: r for r in after['results']}
    for old, new in zip(reports[0]['anchors'], reports[1]['anchors']):
        if not new['source_present']:
            continue
        result = after_records[new['record_id']]
        proposals = result.get('mapreduce_audit', {}).get('proposals', [])
        map_keys = {p['choice_key'] for p in proposals
                    if any(q in p.get('direct_quote', '') for q in [new['quote']] + new.get('equivalent_quotes', []))}
        map_selected = {'VOC-' + k[1:] for k in map_keys}
        map_required = sorted(set(new['required']) & map_selected)
        map_hits += len(map_required)
        changes.append({'record_id': new['record_id'], 'quote': new['quote'], 'basis': new['basis'],
            'before_missing': old.get('missing_required'), 'after_missing': new.get('missing_required'),
            'before_wrong': old.get('forbidden_hits'), 'after_wrong': new.get('forbidden_hits'),
            'map_required_present': map_required,
            'map_recalled_but_not_delivered': sorted(set(map_required) & set(new.get('missing_required') or [])),
            'definition_overlap_review_only': new.get('review_only', [])})
    return {'comparison_scope': '同一随机样本及同一逐原文参考锚点；非完整人工金标准',
        'same_source_ids': set(r['document']['record_id'] for r in before_subset['results']) == ids,
        'before_counts': stats(before_subset), 'after_counts': stats(after),
        'before_reference': reports[0], 'after_reference': reports[1], 'changes': changes,
        'map_required_anchor_hits': map_hits,
        'limitations': ['仅锚点命中率与禁用标签检查，不等于全数据精确率/召回率。',
            '本版本包含MapReduce、定位恢复及定义提示优化，不能将全部变化单独归因于并行。',
            '标签条数或切片条数增加不等于质量改善；字典缺项与定义交叉需要业务复核。']}

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('before', type=Path); parser.add_argument('after', type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    read = lambda path: json.loads(path.read_text(encoding='utf-8'))
    report = compare(read(args.before), read(args.after), read(Path(__file__).with_name('independent_label_anchors_v59.json')))
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k: report[k] for k in ['same_source_ids', 'before_counts', 'after_counts']}, ensure_ascii=False))
    for name in ['before_reference', 'after_reference']:
        print(name, {k: report[name][k] for k in ['processed_required_tags', 'hit_required_tags', 'missed_required_tags',
                                                'processed_forbidden_checks', 'forbidden_tag_hits', 'reference_errors']})
