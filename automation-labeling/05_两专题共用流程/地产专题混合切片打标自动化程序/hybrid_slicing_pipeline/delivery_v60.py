"""Visible-schema integration plus independently grounded exclusion decisions."""
import copy
import delivery_v59 as integrated
import bounded_structural_review_v59 as original_bounded
import bounded_visible_contract_v60 as visible
from comment_identity_protocol_v59 import obj, TEXT, KEYS, resolve
from prose_speaker_catalog import source_catalog

VERSION = 'delivery-v11.60-visible-response-contract-independent-exclusion-20261010'
_scope_review = integrated.scope.review
_process_document = integrated.previous.process_document
_check_exclusion = integrated.check_exclusion


def scope_review(text, parent_context, doc, runner):
    decision, calls, audit = _scope_review(text, parent_context, doc, runner)
    if not decision['exclude']:
        decision['_scope_call_metrics'] = calls
        return decision, calls, audit
    schema = obj({'allow_exclusion': {'type': 'boolean'}, 'source_keys': KEYS,
                  'why': TEXT, 'confidence': {'type': 'number', 'minimum': 0, 'maximum': 1}})
    system = '''独立核查完整评论是否真的应当从住宅口碑研究排除，不默认认可先前分类。
住宅选择比较、观望、赞同、抱怨、提问，即使没有项目名和产品参数，也应保留。
父文只帮助确认讨论是否住宅，不迁移配置或态度。对象不清是待核，不是内容无关。
只有明确是餐饮点餐、招聘薪资、非地产电商、无研究关系的聊天才可允许排除。
若前判分类与理由自相矛盾，或理由承认住宅选择/评价却排除，应否决排除。
source_keys引用完整评论中的实际目录键，不能用父文配置代替评论事实。不确定则allow_exclusion=false。'''
    raw, metrics, extra, errors = visible.review(system,
        {'source_text': text, 'source_catalog': source_catalog(text),
         'parent_context_for_scope_only': parent_context, 'previous_decision_to_question': decision},
        schema, doc, '评论排除决定独立有据核查-v11.60', runner)
    calls += metrics
    audit.append({'independent_exclusion_check': extra})
    confirmed = not errors and raw['allow_exclusion'] and raw['confidence'] >= .9
    confirmed = confirmed and bool(resolve(raw['source_keys'], source_catalog(text)))
    if not confirmed:
        decision = dict(decision, exclude=False, needs_review=True,
            issues=list(decision['issues']) + ['排除决定未获独立有据确认，保留完整评论审核'],
            independent_exclusion_check=extra)
    decision['_scope_call_metrics'] = calls
    return decision, calls, audit


def check_exclusion(*args):
    excluded, unit, audit, metric = _check_exclusion(*args)
    calls = audit.get('_scope_call_metrics') or []
    # The original process explicitly consumes these three additional slots.
    # Two bounded stages have at most four logical requests in total.
    for name, value in zip(('recovery_call', 'countercheck_call', 'countercheck_recovery_call'), calls[1:]):
        metric[name] = value
    return excluded, unit, audit, metric


def check_unit(*args):
    output, audit, calls = integrated.check_unit(*args)
    selection = audit.get('full_dictionary_selection') or []
    selector_valid = bool(selection) and not selection[-1].get('protocol_issues')
    # The selector may return valid empty labels. That is not a recall proof;
    # independent anchors and all-source review remain separate requirements.
    invalid_reference = any('引用未通过' in issue for issue in audit['issues'])
    fatal_protocol = any(issue.startswith('$') or 'API未成功' in issue
                         for issue in audit['issues'] + output.get('uncertainties', []))
    audit['processing_contract_complete'] = selector_valid and not invalid_reference and not fatal_protocol
    return output, audit, calls


def process_document(*args):
    result = _process_document(*args)
    failed = [a.get('case_id') for a in result.get('local_acceptance', [])
              if a.get('processing_contract_complete') is False]
    if failed:
        result['complete'] = False
        result['audit'].append({'原因': '局部标签/证据/文案协议尚未完成，不能把空输出当处理成功',
                                'failed_cases': failed, '需人工审核': True})
    return result


def activate():
    integrated.activate()
    original_bounded.review = visible.review
    integrated.bounded = visible.review
    integrated.prose.bounded = visible.review
    integrated.scope.bounded = visible.review
    integrated.final_boundary.bounded = visible.review
    integrated.scope.review = scope_review
    pipeline = integrated.previous
    pipeline.VERSION = VERSION
    pipeline.IMPLEMENTATION_FILES = list(dict.fromkeys(pipeline.IMPLEMENTATION_FILES +
        ['delivery_v60.py', 'bounded_visible_contract_v60.py']))
    pipeline.check_unit = check_unit
    pipeline.check_exclusion = check_exclusion
    pipeline.process_document = process_document


if __name__ == '__main__':
    activate()
    integrated.previous.main()
