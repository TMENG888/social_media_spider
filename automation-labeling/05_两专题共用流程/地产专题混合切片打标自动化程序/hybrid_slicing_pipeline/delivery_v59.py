"""Integrated v59 entrypoint, isolated from the live frozen v58 process.

Activate only in this executable's process. Source inputs and old checkpoints
are never patched. All API phases share the original runner's semaphore.
"""
import copy
from concurrent.futures import ThreadPoolExecutor
import delivery_v11 as previous
import full_dictionary_selection_v59 as selection
import label_target_binding_v59 as binding
import duplicate_target_projection_v59 as projection
import literal_article_names_v59 as names
import comment_identity_protocol_v59 as identity
import comment_scope_v59 as scope
import semantic_prose_recovery_v59 as prose
import final_boundary_v59 as final_boundary
from bounded_structural_review_v59 import review as bounded
from prose_speaker_catalog import source_catalog

VERSION = 'delivery-v11.59-integrated-dictionary-target-projection-comment-protocol-20261010'
FILES = ['delivery_v59.py', 'full_dictionary_selection_v59.py', 'label_target_binding_v59.py',
         'duplicate_target_projection_v59.py', 'literal_article_names_v59.py',
         'comment_identity_protocol_v59.py', 'comment_scope_v59.py',
         'semantic_prose_recovery_v59.py', 'comment_core_coverage_v59.py',
         'bounded_structural_review_v59.py', 'final_boundary_v59.py']
_check_exclusion = previous.check_exclusion
_quote_partition = previous.quote_partition
_detach = previous.detach_unsupported_projects


def final_scope_review(doc, plan, segments, runner):
    out, new_segments, audit, calls, issues = final_boundary.review(doc, plan, segments, runner, _quote_partition)
    if not issues:
        # The original process retains this list reference downstream. Replace
        # its contents atomically only after the entire source partition passes.
        segments[:] = new_segments
    return out, audit, calls, issues


def comment_partition(raw, text, kind):
    if kind != '评论':
        return _quote_partition(raw, text, kind)
    # Boundary is the stored source by contract, not a model-confidence claim.
    unit = {'relevant': True, 'scope_reason': '完整主评论及全部已有回复，禁止拆分',
            'object_quote': None, 'project_ids': [], 'project_evidence': [],
            'publisher_role': '不明', 'expression_types': [], 'emotions': [],
            'summary': None, 'practice': None, 'labels': [],
            'confidence': {'boundary': 1.0, 'summary': None, 'project': None, 'metadata': None},
            'uncertainties': [], 'source_start_id': 1, 'source_end_id': 1, 'start_quote': text[:40]}
    return {'units': [unit], 'initial_plan_audit': copy.deepcopy(raw)}, [
        {'id': 1, 'start': 0, 'end': len(text), 'text': text}], []


def check_exclusion(doc, unit, segments, runner):
    if doc['kind'] != '评论':
        return _check_exclusion(doc, unit, segments, runner)
    parent = previous.p.base.choose_source(doc['parent'])[1]
    decision, calls, audit = scope.review(doc['text'], parent, doc, runner)
    output = copy.deepcopy(unit)
    output['relevant'] = not decision['exclude']
    output['_scope_unresolved'] = False  # uncertainty retains the whole reviewable row
    output.setdefault('uncertainties', []).extend(decision['issues'])
    result = dict(decision, protocol_audit=audit, direct_quote=doc['text'],
                  content_kind=decision.get('kind'), why=decision.get('why') or '相关性不确定，保留审核')
    metric = dict(calls[0])
    if len(calls) > 1:
        metric['recovery_call'] = calls[1]
    return decision['exclude'], output, result, metric


def review_metadata(doc, units, segments, business, runner):
    literal, calls, audit, errors = names.review(doc, runner)
    output, metadata_audit, mc, issues = names.review_metadata(doc, units, segments, business, literal, runner)
    for unit in output:
        decisions = unit.get('metadata_identity_audit') or {}
        verified = {}
        for field in ('brand', 'entity', 'project_name', 'city'):
            decision = decisions.get(field)
            if (isinstance(decision, dict) and unit.get(field) == decision.get('value')
                    and type(decision.get('confidence')) in (int, float)
                    and .9 <= decision['confidence'] <= 1):
                verified[field] = decision['confidence']
        if set(verified) == {'brand', 'entity', 'project_name', 'city'}:
            unit.setdefault('confidence', {})['metadata'] = min(verified.values())
            if unit.get('project_name'):
                unit['confidence']['project'] = verified['project_name']
    return output, {'literal_names': audit, 'metadata': metadata_audit}, calls + mc, errors + issues


def expression_values(text, doc, runner):
    def item(values):
        return identity.obj({'value': {'type': 'string', 'enum': sorted(values)},
            'source_keys': identity.KEYS, 'why': identity.TEXT,
            'confidence': {'type': 'number', 'minimum': 0, 'maximum': 1}})
    schema = identity.obj({'expressions': {'type': 'array', 'items': item(previous.expression_review.EXPRESSIONS)},
        'emotions': {'type': 'array', 'items': item(previous.expression_review.EMOTIONS)}})
    system = previous.expression_review.SYSTEM + '''
本轮不生成摘要，只返回expressions和emotions；每项的value、source_keys、why、confidence按结构。
相同类别汇总所有支持的实际原文键，每个value恰好一次；不同发言者正负态度可同时保留。
source_keys只选source_catalog真实键，不是昵称或子评论编号。'''
    raw, calls, audit, errors = bounded(system, {'source_text': text, 'source_catalog': source_catalog(text)},
                                      schema, doc, '原文表达情绪结构化核验-v11.59', runner)
    output = {'expression_types': [], 'emotions': []}
    if errors:
        return output, calls, audit, errors
    for field, target in [('expressions', 'expression_types'), ('emotions', 'emotions')]:
        seen = set()
        for value in raw[field]:
            if value['value'] in seen:
                errors.append('表达/情绪类别重复：' + value['value']); continue
            seen.add(value['value'])
            if not identity.resolve(value['source_keys'], source_catalog(text)) or value['confidence'] < .9:
                errors.append('表达/情绪证据或置信度不足：' + value['value']); continue
            output[target].append(value['value'])
        if not output[target]:
            errors.append('未取得有效' + target)
    return output, calls, audit, errors


def check_unit(doc, unit, i, segments, taxonomy, runner):
    index = previous.p.v.registry(taxonomy, doc['topic'])
    text = previous.p.v.legacy.interval(segments, unit['source_start_id'], unit['source_end_id'])
    context = unit.get('object_quote') or ''
    out = copy.deepcopy(unit)
    out['labels'] = []
    calls, issues, ambiguities, targets_audit = [], [], [], []
    if context and context not in doc['text']:
        issues.append('对象上下文无法原样定位'); context = ''
    if doc['kind'] == '评论':
        business = previous.p.base.load_business()
        targets, tc, ta, ti = identity.review_projects(text, previous.p.base.choose_source(doc['parent'])[1],
                                                       business['projects'], doc, runner)
        role, rc, ra, ri = identity.review_role(text, doc, runner)
        calls += tc + rc; issues += ti + ri
        out['_v59_targets'] = targets
        targets_audit = {'projects': ta, 'role': ra}
        out['publisher_role'] = role
        out['project_ids'] = [t['id'] for t in targets if t['id'] is not None]
        out['project_evidence'] = [{'id': t['id'],
            'evidence': t['evidence']['comment_quote'].split('...')[0], 'why': t['evidence']['why']}
            for t in targets if t['id'] is not None]
        out.setdefault('confidence', {})['project'] = min((t['evidence']['confidence'] for t in targets), default=None)
        raw_role = ra[-1].get('raw_response') if ra else None
        out['confidence']['metadata'] = raw_role.get('confidence') if raw_role and not ri else None
    selected, sc, sa, si = selection.review(text, index, context, doc, runner)
    calls += sc; issues += si
    # First generation is a proposal too. Never discard it merely because a
    # second model did not recall it; independently bind the union, not accept it.
    proposals = {t['choice_key']: t for t in selected}
    for tag in unit.get('labels') or []:
        if isinstance(tag, dict) and tag.get('choice_key') in index:
            proposals.setdefault(tag['choice_key'], tag)
    def one(key):
        return key, binding.review(text, index[key], context, doc, runner)
    with ThreadPoolExecutor(max_workers=10) as pool:
        checked = list(pool.map(one, sorted(proposals)))
    binding_audit = []
    confidence_values = []
    for key, (accepted, bc, ba, bi) in checked:
        calls += bc
        binding_audit.append({'choice_key': key, 'accepted': accepted, 'audit': ba, 'issues': bi})
        if not accepted:
            raw = ba[-1].get('raw_response') if ba else None
            if raw and raw.get('status') == 'unsupported' and not ba[-1].get('protocol_issues'):
                continue  # explicit semantic rejection is audited, not label success
            ambiguities.append({'choice_key': key, 'reason': '；'.join(bi) or '定义核验不确定'})
            issues += bi; continue
        raw = ba[-1]['raw_response']
        quote = identity.resolve(raw['property_keys'], source_catalog(text))
        oq = identity.resolve(raw['object_keys'], source_catalog(text))
        state, why = previous.p.v.evidence_guard(text, index[key], oq)
        if state == 'rejected':
            binding_audit[-1]['program_rejection'] = why
            continue
        if state == 'uncertain':
            issues.append('标签对象硬约束待核：' + key + ' ' + why)
        out['labels'].append({'choice_key': key, 'direct_quote': quote,
            'evidence_start_id': unit['source_start_id'], 'evidence_end_id': unit['source_end_id'],
            'object_start_id': None, 'object_end_id': None, 'object_quote': oq,
            'why': raw['why'], 'project_ids': out.get('project_ids') or [],
            'confidence': raw['confidence']})
        confidence_values.append(raw['confidence'])
    field = 'practice' if doc['topic'] == previous.p.base.T1 else 'summary'
    value, pc, pa, pi = prose.recover(text, context, field, doc, runner)
    calls += pc; issues += pi
    out[field] = value['text'] if value else None
    out.setdefault('confidence', {})['summary'] = value['confidence'] if value else None
    if value:
        confidence_values.append(value['confidence'])
    expression_audit = []
    if doc['topic'] == previous.p.base.T2:
        values, ec, expression_audit, ei = expression_values(text, doc, runner)
        calls += ec; issues += ei; out.update(values)
    out.setdefault('uncertainties', []).extend(issues)
    out['self_check'] = {'pass': not issues and not ambiguities,
                         'confidence': min(confidence_values) if confidence_values else None,
                         'issues': issues}
    return out, {'case_id': doc['record_id'] + '-U' + str(i + 1),
        'full_dictionary_selection': sa, 'label_target_checks': binding_audit,
        'independent_prose_audit': pa, 'expression_audit': expression_audit,
        'comment_identity_audit': targets_audit, 'issues': issues, 'ambiguous': ambiguities}, calls


def detach(doc, unit, business):
    if doc['kind'] == '评论' and '_v59_targets' in unit:
        return unit  # source-owned independent relation evidence, not parent configuration
    return _detach(doc, unit, business)


def comment_projects(result, business, runner):
    if result['document']['kind'] != '评论' or not result['rows']:
        return result
    units = result.get('grounding_response', {}).get('units', [])
    targets = units[0].get('_v59_targets', []) if units else []
    for row in result['rows']:
        row.update(project_id=[t['id'] for t in targets], 项目名称=[t['name'] for t in targets],
                   项目角色=[t['role'] for t in targets])
        if not targets:
            row['备注'] += '；评论项目对象无法确认，未按父文候选数量强制继承'
            row['验收状态'] = '需人工审核'
    for trace in result['traces']:
        trace['项目归属独立核查'] = {'verified_targets': targets, 'protocol_version': VERSION}
    return result


def source_comment_mapping(doc, row, trace, business):
    """Mapping only: no case-specific text/label/summary repair after inference."""
    if doc['kind'] != '评论':
        return
    original_id = doc['row'].get('文章id')
    value = str(original_id) if original_id is not None and original_id != '' else None
    row['映射文章id'] = value
    trace['评论源表文章id'] = value
    parent_id = doc['parent'].get('文章id')
    trace['父文章平台文章id'] = str(parent_id) if parent_id is not None and parent_id != '' else None
    trace['映射字段口径'] = '平台＋评论文章id关联文章文章id；ODS主键单独追溯'


def duplicate_facts(doc, units, segments, index, runner):
    if doc['kind'] == '评论':
        return units, [], []
    output = copy.deepcopy(units); audit, calls, removed = [], [], set()
    pairs = [(a, b, key) for a, unit in enumerate(units) for b in range(a + 1, len(units))
             for key in sorted({t['choice_key'] for t in unit['labels']} &
                               {t['choice_key'] for t in units[b]['labels']})]
    for a, b, key in pairs:
        left = previous.p.v.legacy.interval(segments, units[a]['source_start_id'], units[a]['source_end_id'])
        right = previous.p.v.legacy.interval(segments, units[b]['source_start_id'], units[b]['source_end_id'])
        decision, dc, da, di = projection.review(left, right, index[key], doc['text'], doc, runner)
        calls += dc
        item = {'unit_a': a, 'unit_b': b, 'choice_key': key, 'decision': decision, 'audit': da, 'issues': di}
        if decision and decision['safe_to_remove']:
            keep = a if decision['keep_side'] == 'A' else b
            drop = b if keep == a else a
            if (keep, key) not in removed:
                output[drop]['labels'] = [t for t in output[drop]['labels'] if t['choice_key'] != key]
                removed.add((drop, key)); item['removed_unit_index'] = drop
        elif di or decision is None or decision['verdict'] in {'uncertain', 'partial_overlap'}:
            for k in (a, b):
                output[k].setdefault('uncertainties', []).append('标签目标事实重叠待核：' + key)
        audit.append(item)
    return output, audit, calls


def activate():
    previous.VERSION = VERSION
    previous.IMPLEMENTATION_FILES = list(dict.fromkeys(previous.IMPLEMENTATION_FILES + FILES))
    previous.quote_partition = comment_partition
    previous.check_exclusion = check_exclusion
    previous.check_unit = check_unit
    previous.identity_metadata.review = review_metadata
    previous.detach_unsupported_projects = detach
    previous.apply_verified_comment_projects = comment_projects
    previous.reconcile_duplicate_facts = duplicate_facts
    previous.final_scope_groups.review = final_scope_review
    previous.p.v.legacy.apply_comment_mapping = source_comment_mapping


if __name__ == '__main__':
    activate()
    previous.main()
