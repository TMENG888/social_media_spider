"""MapReduce production entry point; previous datasets are read-only."""
import copy
from concurrent.futures import ThreadPoolExecutor
import delivery_v75 as current
import delivery_v59 as checks
import delivery_v11 as pipeline
import mapreduce_v76 as mr

VERSION = 'delivery-v76.4-exhaustive-full-source-mapreduce-20261010'

def map_only_selection(*args, **kwargs):
    # The union of exhaustive full-source Maps is checked by check_unit below.
    # Do not run the old full-dictionary selector again and overwrite recall.
    return [], [], [{'selection_source': '全部Map分支证据提议，逐标签独立定义审核'}], []

def duplicate_facts(doc, units, segments, index, runner):
    """Parallel independent pair checks; deterministic application afterwards.

    Equal labels do not imply equal facts. Distinct houses/objects remain unless
    the original semantic projection explicitly proves a redundant same fact.
    """
    if doc['kind'] == '评论':
        return units, [], []
    pairs = [(a, b, key) for a, u in enumerate(units) for b in range(a + 1, len(units))
             for key in sorted({t['choice_key'] for t in u['labels']} &
                               {t['choice_key'] for t in units[b]['labels']})]
    def one(pair):
        a, b, key = pair
        left = pipeline.p.v.legacy.interval(segments, units[a]['source_start_id'], units[a]['source_end_id'])
        right = pipeline.p.v.legacy.interval(segments, units[b]['source_start_id'], units[b]['source_end_id'])
        return pair, checks.projection.review(left, right, index[key], doc['text'], doc, runner)
    with ThreadPoolExecutor(max_workers=10) as pool:
        decisions = list(pool.map(one, pairs))
    output, audit, calls, removed = copy.deepcopy(units), [], [], set()
    for (a, b, key), (decision, cc, aa, ee) in decisions:
        calls += cc
        item = {'unit_a': a, 'unit_b': b, 'choice_key': key, 'decision': decision, 'audit': aa, 'issues': ee}
        if decision and decision['safe_to_remove']:
            keep = a if decision['keep_side'] == 'A' else b
            drop = b if keep == a else a
            if (keep, key) not in removed:
                output[drop]['labels'] = [t for t in output[drop]['labels'] if t['choice_key'] != key]
                removed.add((drop, key)); item['removed_unit_index'] = drop
        elif ee or decision is None or decision['verdict'] in {'uncertain', 'partial_overlap'}:
            for i in (a, b):
                output[i].setdefault('uncertainties', []).append('标签目标事实重叠待核：' + key)
        audit.append(item)
    return output, audit, calls

def process_document(doc, taxonomy, business, runner):
    doc = copy.deepcopy(doc)
    doc['project_context_policy'] = 'independently_verified_only'
    index = pipeline.p.v.registry(taxonomy, doc['topic'])
    parent = pipeline.p.base.choose_source(doc['parent'])[1] if doc['kind'] == '评论' else ''
    proposals, calls, map_audit, errors = mr.run_maps(doc, index, runner, parent)
    plan, segments, boundary_errors, rc, reduce_audit = mr.reduce(doc, proposals, runner, pipeline.quote_partition)
    calls += rc; errors += boundary_errors
    if not plan:
        return {'document': doc, 'rows': [], 'traces': [], 'complete': False, 'calls': calls,
            'audit': [{'原因': 'MapReduce协议未完整通过', 'issues': errors}],
            'mapreduce_audit': {'maps': map_audit, 'reduce': reduce_audit, 'proposals': proposals}}
    routed = mr.route(proposals, segments)
    for unit, labels in zip(plan['units'], routed):
        unit['labels'] = labels
        unit.setdefault('innovation_type', '无明确创新类型')
        unit.setdefault('innovation_level', 'I0 无创新判断')
        unit.setdefault('innovation_evidence', '未取得原文明示升级基线或同类差异依据')
        if errors:
            unit.setdefault('uncertainties', []).append('部分Map协议未完成，不能认定标签全覆盖：' + '；'.join(errors))
    metadata_audit = []
    if doc['topic'] == pipeline.p.base.T1 and doc['kind'] == '文章':
        plan['units'], metadata_audit, cc, ee = checks.review_metadata(doc, plan['units'], segments, business, runner)
        calls += cc
        if ee:
            for u in plan['units']:
                u.setdefault('uncertainties', []).extend(ee)
    units, audits, excluded = [], [], []
    for i, unit in enumerate(plan['units']):
        if doc['kind'] == '评论':
            exclude, unit, scope, metric = checks.check_exclusion(doc, unit, segments, runner)
            calls.append(metric)
            if exclude:
                excluded.append({'原文': doc['text'], '原因': scope['why'], '独立范围复核': scope})
                continue
        # An empty Map proposal is not evidence of irrelevance. Keep it reviewable.
        checked, audit, cc = checks.check_unit(doc, unit, i, segments, taxonomy, runner)
        calls += cc
        checked['_excerpt'] = segments[i]['text']
        if doc['topic'] == pipeline.p.base.T2 and doc['kind'] == '文章':
            checked = pipeline.project_anchors.recover(checked, business['projects'])
        checked = pipeline.detach_unsupported_projects(doc, checked, business)
        units.append(checked); audits.append(audit)
    units, duplicate_audit, cc = duplicate_facts(doc, units, segments, index, runner)
    calls += cc
    selected = {a['choice_key'] for u in units for a in u['labels']}
    ambiguous = {a['choice_key']: a for audit in audits for a in audit['ambiguous'] if a['choice_key'] not in selected}
    raw = {'units': units, 'coverage_scope': 'slice_local', 'coverage': {
        'supported_keys': sorted(selected), 'unsupported_keys': sorted(set(index) - selected - set(ambiguous)),
        'ambiguous': list(ambiguous.values()), 'confidence': min((u['self_check']['confidence'] or 0 for u in units), default=None),
        'issues': [issue for audit in audits for issue in audit['issues']]},
        'exclusion_reason': '；'.join(x['原因'] for x in excluded) if not units else None,
        'exclusion_confidence': 1.0 if excluded else None, 'unmatched_information': []}
    doc['semantic_segments'] = segments
    payload = pipeline.p.v.legacy.request_payload(doc, taxonomy, business)
    payload.update(source_text=doc['text'], source_segments=segments)
    raw = pipeline.p.reanchor_literal_evidence(raw, doc)
    result = pipeline.p.v.assemble(doc, taxonomy, business, raw, calls[0], payload,
        pipeline.p.v.coverage_check(raw, index), True)
    result.update(calls=calls, full_source_partition=plan, local_acceptance=audits,
        grounding_response=raw, grounding_issues=[], excluded_intervals=excluded,
        duplicate_fact_audit=duplicate_audit, mapreduce_audit={'maps': map_audit,
            'reduce': reduce_audit, 'proposals': proposals, 'metadata': metadata_audit})
    result['audit'] += excluded
    if errors:
        result['complete'] = False
        result['audit'].append({'原因': '部分Map协议未完成', 'issues': errors})
    result = pipeline.apply_verified_comment_projects(result, business, runner)
    for row, trace in zip(result['rows'], result['traces']):
        trace['MapReduce版本'] = VERSION
        if row.get('情绪态度'):
            values = row['情绪态度'].split(';')
            if len(values) > 1 and '无态度' in values:
                trace['原细粒度情绪'] = values
                row['情绪态度'] = ';'.join(v for v in values if v != '无态度')
    # Independently exclude only empty-tag ranges proven to contain no product
    # facts; absence of a tag never by itself erases a source interval.
    if doc['topic'] == pipeline.p.base.T1 and doc['kind'] == '文章':
        from bounded_visible_contract_v60 import review as bounded
        from prose_speaker_catalog import source_catalog
        kept_rows, kept_traces = [], []
        for row, trace in zip(result['rows'], result['traces']):
            if not row['标签明细']:
                text = row['原文摘录']
                decision, cc, aa, ee = bounded(current.SCOPE_SYSTEM,
                    {'full_source_text': doc['text'], 'slice_text': text, 'source_catalog': source_catalog(text)},
                    current.SCOPE_SCHEMA, doc, '无标签产品片研究范围独立核查-v11.75', runner)
                result['calls'] += cc
                trace['无标签产品片范围核查'] = aa
                if not ee and current.scope_decision(text, decision):
                    result['excluded_intervals'].append({'原文': text, '原因': decision['why'], '原单元ID': row['unit_id']})
                    result['audit'].append({'原因': decision['why'], '排除单元追溯': trace})
                    continue
            kept_rows.append(row); kept_traces.append(trace)
        result['rows'], result['traces'] = kept_rows, kept_traces
    return result

def activate():
    current.activate()
    checks.selection.review = map_only_selection
    checks.binding.SYSTEM += '''
核查特别约束：不得把“当前室内听不到飞机，户外听得到”否决为无噪音无标签。
交通噪音标签记录来源、影响或室内外差异，不要求负面影响成立；否认/缓解也是该话题事实。
品牌准时交付必须有已发生交付和准时的明示事实，未来预计某年交房绝不证明准时交付。
土地规划条件层高需要土地规划条件证据，现有住宅/户型层高不是土地规划层高。
色彩体系需要明确色彩描述，单纯法式装修风格只能检查整体设计风格，不能推导色彩。
机场运行中的起降和驱鸟相关噪音，要结合原文机场运行背景检查，不因驱鸟二字就否决交通噪音。
户内厨房烟道口密封施工不能仅因共用烟道就变成公区设施，工法样板间也不是公区属性证据。
说明中的例子不强制逐词出现；但物理对象、属性、模态必须有据。
每个why控制60字以内。不因为试图精确就添加定义没有的门槛。'''
    pipeline.process_document = process_document
    pipeline.VERSION = VERSION
    pipeline.IMPLEMENTATION_FILES = list(dict.fromkeys(pipeline.IMPLEMENTATION_FILES + ['delivery_v76.py', 'mapreduce_v76.py']))

if __name__ == '__main__':
    activate()
    pipeline.main()
