"""Offline delivery gate: emitted defaults are not completed metadata evidence.

Never modifies generation checkpoints or sends requests. Explicit, source-bound
independent corrections may complete metadata; they never resolve label holds.
"""
import json
import sys
import time
from collections import Counter

ALLOWED = {
    '表达类型': {'事实介绍', '正向评价', '负向评价', '中性评价', '需求表达', '提问咨询', '比较评价'},
    '情绪态度': {'无态度', '中性', '正向', '负向'},
}
RAW_FIELDS = {'表达类型': 'expressions', '情绪态度': 'emotions'}


def legal_values(value, field):
    return (isinstance(value, list) and bool(value)
            and all(isinstance(x, str) and x in ALLOWED[field] for x in value)
            and not (field == '情绪态度' and {'无态度', '中性'} <= set(value)))


def record_issues(record, repair_loader, corrections):
    """Inspect authoritative raw supported drafts, not generated row defaults."""
    issues = []
    if record.get('state') != 'accepted':
        return issues
    if not record.get('rows'):
        return [{'record_id': record['record_id'], 'unit_id': None,
                 'field': None, 'reason': 'accepted来源没有有效单元'}]
    for row in record['rows']:
        rid, uid = record['record_id'], row['unit_id']
        proof = repair_loader(rid, uid)
        outcome = (proof or {}).get('outcome', {})
        history = outcome.get('history') or []
        draft = history[-1].get('draft') if history else None
        source_matches = (outcome.get('state') == 'accepted'
                          and outcome.get('row', {}).get('unit_id') == uid
                          and outcome.get('row', {}).get('原始摘录') == row.get('原始摘录'))
        correction = corrections.get((rid, uid))
        if correction and correction.get('source_quote') != row.get('原始摘录'):
            raise ValueError('Metadata correction no longer matches exact source quote')
        for field, rawfield in RAW_FIELDS.items():
            corrected = (correction or {}).get('fields', {}).get(field)
            if corrected is not None:
                if not isinstance(corrected, str) or not legal_values(corrected.split(';'), field):
                    raise ValueError('Invalid source-specific metadata correction')
                # Application/provenance is separately verified at final export.
                continue
            supplied = draft.get(rawfield) if isinstance(draft, dict) else None
            valid = (source_matches and isinstance(draft, dict)
                     and draft.get('decision') == 'supported'
                     and legal_values(supplied, field))
            expected = ';'.join(dict.fromkeys(supplied)) if valid else None
            if valid and row.get(field) == expected:
                continue
            issues.append({'record_id': rid, 'unit_id': uid, 'field': field,
                           'raw_field': rawfield, 'raw_value': supplied,
                           'saved_value': row.get(field),
                           'source_quote': row.get('原始摘录'),
                           'reason': ('原始supported回复无有效非空枚举或缺同源修复证据；生成默认值不能证明完成'
                                      if not valid else '保存值与原始合法枚举不一致，需逐条核验')})
    return issues


def audit_results(results, audit, repair_loader):
    corrections = {(c['record_id'], c['unit_id']): c for c in audit['corrections']}
    if len(corrections) != len(audit['corrections']):
        raise ValueError('Duplicate metadata corrections')
    issues = [issue for record in results.values()
              for issue in record_issues(record, repair_loader, corrections)]
    return {'passed': not issues, 'is_partial_not_delivery': True,
            'machine_accepted_sources': sum(r.get('state') == 'accepted' for r in results.values()),
            'blocked_sources': sorted({x['record_id'] for x in issues}),
            'issue_count_by_field': dict(Counter(x['field'] for x in issues)),
            'issues': issues, 'generation_checkpoints_unchanged': True,
            'default_values_not_completion_evidence': True,
            'network_calls': 0, 'human_gold': False, 'observed_at': time.time()}


def current_audit(results):
    import voc_batch_v99 as v

    def load_repair(rid, uid):
        path = v.repair_path(rid, uid)
        return v.read(path) if path.exists() else None

    return audit_results(results, v.read(v.OUT/'independent_metadata_corrections.json'), load_repair)


def main():
    import voc_batch_v99 as v
    v.VERSION = v.read(v.OUT/'run_status.json')['version']
    report = current_audit(v.known_results(v.read(v.OUT/'candidate_documents.json')))
    v.save('independent_metadata_completion_partial.json', report)
    print(json.dumps({k: value for k, value in report.items() if k != 'issues'}, ensure_ascii=False))


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
