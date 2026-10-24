"""Read-only aggregation of independent source/contract/semantic diagnostics.

No aggregate accuracy, no perfect score for missing sources, no output repairs.
The diagnostics cover specific observed requirements, not exhaustive gold data.
"""
import argparse
import importlib
import json
from pathlib import Path
import delivery_v11 as pipeline
import verify_original_csv_sources as original
import verify_delivery_v4 as contract
import verify_dictionary_backfill_v8 as dictionary
from evaluate_independent_label_anchors_v59 import evaluate

SEMANTIC_MODULES = (
    'verify_observed_workmanship_cases', 'verify_observed_asr_identity_cases',
    'verify_observed_precision_v49', 'verify_observed_source_categories_v53',
    'verify_observed_compare_granularity_v53', 'verify_observed_project_context_v55',
    'verify_extended_article_quality', 'verify_extended_comment_quality',
    'verify_observed_identity_v59', 'verify_observed_label_target_v59',
    'verify_comment_comparison_qualifiers_v59',
)


def scope_check(data, sample):
    expected = [d['record_id'] for d in sample['documents']]
    actual = [r['document']['record_id'] for r in data.get('results', [])]
    return {'planned_sources': len(expected), 'completed_sources': len(actual),
            'missing_sources': sorted(set(expected) - set(actual)),
            'unexpected_sources': sorted(set(actual) - set(expected)),
            'duplicate_source_ids': sorted({rid for rid in actual if actual.count(rid) > 1}),
            'incomplete_sources': [r['document']['record_id'] for r in data.get('results', [])
                                   if not r.get('complete')]}


def audit(data, sample):
    taxonomy = pipeline.p.base.load_taxonomy(pipeline.p.v.legacy.TAXONOMY)
    scope = scope_check(data, sample)
    reports = {'contract': contract.verify(data) if 'tables' in data else
                   {'errors': ['快照没有最终交付表，完整交付契约尚未核验'], 'status': 'unverified'},
               'dictionary': dictionary.verify(data, {t['tag_id']: t for t in taxonomy}),
               'original_sources': original.inspect(data, original.base.read_csv(original.POST),
                                                      original.base.read_csv(original.COMMENT))}
    for name in SEMANTIC_MODULES:
        reports[name] = importlib.import_module(name).inspect(data)
    reference = json.loads(Path(__file__).with_name('independent_label_anchors_v59.json').read_text(encoding='utf-8'))
    anchors = evaluate(data, reference, {t['tag_id'] for t in taxonomy})
    rows = [u for r in data.get('results', []) for u in r.get('rows', [])]
    inventory = {'rows': len(rows),
                 'automatic_rows': sum(u.get('验收状态') == '自动通过' for u in rows),
                 'manual_rows': sum(u.get('验收状态') == '需人工审核' for u in rows),
                 'blank_prose_rows': [u['unit_id'] for u in rows
                     if not (u.get('具体产品做法') or u.get('观点摘要'))],
                 'empty_tag_rows': [u['unit_id'] for u in rows if not u.get('标签明细')]}
    return {'scope': scope, 'inventory': inventory, 'reports': reports, 'anchors': anchors,
            'limitations': '独立原文和定义锚点不是全样本人类金标准；结构、字典合法性和模型置信度不证明精确率或召回率。空标签需要逐事实核查，不自动算漏标。'}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('input', type=Path)
    parser.add_argument('--sample', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = audit(json.loads(args.input.read_text(encoding='utf-8')),
                   json.loads(args.sample.read_text(encoding='utf-8')))
    pipeline.p.base.save_json(args.output, report)
    print(pipeline.p.base.dumps({'scope': report['scope'], 'inventory': report['inventory'],
        'diagnostic_errors': {name: r.get('errors', r.get('contract_errors', ['诊断报告没有可解释的错误字段']))
                              for name, r in report['reports'].items()},
        'anchor_misses': report['anchors']['missed_required_tags'],
        'anchor_forbidden_hits': report['anchors']['forbidden_tag_hits']}))


if __name__ == '__main__':
    main()
