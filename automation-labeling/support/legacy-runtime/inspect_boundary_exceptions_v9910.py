"""Bounded, offline diagnosis of saved failed boundary stages; never accepts.

Formal replies stay intact. Both original anchors and the live implementation's
literal shortening are inspected, because cache formatting is not a semantic
failure and a syntactically fixed partition is not semantic acceptance.
"""
import argparse
import copy
import re
import sys
import time
from functools import lru_cache

import voc_batch_v99 as v
from prepare_reduce_recovery_v99 import normalize_quote

REVISION = 'voc-v99.10-article-reuse-missing-only-20261015'


def literal_recovery_candidate(text, raw):
    """Propose only uniquely determined starts; never a semantic approval.

    An invalid model occurrence may be restored from a unique exact quote. An
    ambiguous repeated quote needs exactly one global, source-ordered assignment.
    Whitespace equivalence must match every non-whitespace character exactly.
    """
    if not isinstance(raw, dict) or not isinstance(raw.get('units'), list) or not raw['units']:
        return {'prepared': False, 'reason': 'No saved model units', 'accepted_for_generation_or_statistics': False}
    choices = []; audit = []
    compact = ''.join(c for c in text if not c.isspace())
    inverse = [i for i, c in enumerate(text) if not c.isspace()]
    for i, unit in enumerate(raw['units']):
        quote = unit.get('start_quote'); ordinal = unit.get('start_occurrence')
        if not isinstance(quote, str) or not quote:
            return {'prepared': False, 'reason': 'Empty model anchor', 'accepted_for_generation_or_statistics': False}
        hits = [m.start() for m in re.finditer('(?='+re.escape(quote)+')', text)]
        method = 'exact_literal'
        if hits and type(ordinal) is int and 1 <= ordinal <= len(hits):
            candidates = [hits[ordinal-1]]
        elif hits:
            candidates = hits
        else:
            needle = ''.join(c for c in quote if not c.isspace())
            positions = [m.start() for m in re.finditer('(?='+re.escape(needle)+')', compact)] if needle else []
            if len(positions) != 1:
                return {'prepared': False, 'reason': 'Anchor lacks a unique exact/whitespace-only source match',
                    'unit_index': i, 'accepted_for_generation_or_statistics': False}
            candidates = [inverse[positions[0]]]; method = 'unique_whitespace_only_equivalence'
        if len(candidates) > 200 or len(raw['units']) > 100:
            return {'prepared': False, 'reason': 'Literal ambiguity exceeds bounded offline search',
                'accepted_for_generation_or_statistics': False}
        choices.append(candidates)
        audit.append({'unit_index': i, 'original_quote': quote, 'original_occurrence': ordinal,
            'possible_starts': candidates, 'rule': method})

    @lru_cache(None)
    def assignments(index, previous):
        if index == len(choices): return ((),)
        answers = []
        for start in choices[index]:
            if start <= previous or (index == 0 and start != 0): continue
            for tail in assignments(index+1, start):
                answers.append((start,)+tail)
                if len(answers) == 2: return tuple(answers)
        return tuple(answers)

    possibilities = assignments(0, -1)
    if len(possibilities) != 1:
        # Existing core can reorder already unique literal starts. Do not use
        # this branch to choose between repeated anchors or merge two units.
        if all(len(c) == 1 for c in choices) and len({c[0] for c in choices}) == len(choices) and min(c[0] for c in choices) == 0:
            starts = [c[0] for c in choices]
        else:
            return {'prepared': False, 'reason': 'No unique source-owned ordered assignment',
                'possible_assignment_count_capped_at_two': len(possibilities),
                'accepted_for_generation_or_statistics': False}
    else:
        starts = list(possibilities[0])
    fixed = copy.deepcopy(raw)
    for i, start in enumerate(starts):
        quote = text[start:start+35]
        hits = [m.start() for m in re.finditer('(?='+re.escape(quote)+')', text)]
        fixed['units'][i].update(start_quote=quote, start_occurrence=hits.index(start)+1)
        audit[i].update(source_start=start, literal_quote=quote, normalized_occurrence=hits.index(start)+1)
    fixed, errors = v.partition.order_literal_units(text, fixed, [])
    if errors:
        return {'prepared': False, 'reason': 'Source-owned candidate failed current location validation',
            'errors': errors, 'accepted_for_generation_or_statistics': False}
    plan, segments, errors = v.partition.build_plan(text, fixed, v.quote_partition)
    if errors or not plan:
        return {'prepared': False, 'reason': 'Source-owned candidate failed full-source partition validation',
            'errors': errors, 'accepted_for_generation_or_statistics': False}
    return {'prepared': True, 'location_only_candidate': fixed, 'position_audit': audit,
        'segments': segments, 'status': 'requires_independent_full_source_semantic_boundary_review',
        'confidence_and_uncertainties_unchanged': True, 'accepted_for_generation_or_statistics': False}


def literal_anchor_diagnostics(text, raw):
    if not isinstance(raw, dict) or not isinstance(raw.get('units'), list):
        return {'has_units': False, 'accepted_for_generation_or_statistics': False}
    normalized = copy.deepcopy(raw); shortenings = []; anchors = []
    for i, unit in enumerate(raw['units']):
        quote = unit.get('start_quote'); occurrence = unit.get('start_occurrence')
        if not isinstance(quote, str) or not quote:
            anchors.append({'unit_index': i, 'invalid_or_empty_quote': True}); continue
        positions = [m.start() for m in re.finditer('(?='+re.escape(quote)+')', text)]
        selected = positions[occurrence-1] if type(occurrence) is int and 1 <= occurrence <= len(positions) else None
        whitespace_candidates = []
        if not positions:
            compact = []; offsets = []
            for n, char in enumerate(text):
                if not char.isspace(): compact.append(char); offsets.append(n)
            needle = ''.join(c for c in quote if not c.isspace())
            if needle:
                hits = [m.start() for m in re.finditer('(?='+re.escape(needle)+')', ''.join(compact))]
                whitespace_candidates = [offsets[n] for n in hits]
        anchors.append({'unit_index': i, 'original_quote': quote, 'original_occurrence': occurrence,
            'exact_positions': positions, 'selected_start': selected,
            'whitespace_only_positions_not_accepted': whitespace_candidates,
            'unique_literal_wrong_ordinal': len(positions) == 1 and occurrence != 1,
            'confidence_unchanged': unit.get('confidence'), 'uncertainties_preserved': unit.get('uncertainties')})
        if len(quote) > 35:
            fixed, evidence = normalize_quote(text, unit)
            if fixed is not None: normalized['units'][i] = fixed; shortenings.append(evidence)
    original_starts, original_errors = v.partition.boundary.locate(text, raw)
    starts, errors = v.partition.boundary.locate(text, normalized)
    ordered, order_errors = v.partition.order_literal_units(text, normalized, [])
    return {'has_units': True, 'anchors': anchors, 'original_located_starts': original_starts,
        'original_location_errors': original_errors, 'literal_shortening_audit': shortenings,
        'shortened_located_starts': starts, 'shortened_location_errors': errors,
        'current_order_validation_errors': order_errors,
        'has_duplicate_exact_starts': len(starts) != len(set(starts)),
        'coverage_starts_at_source_zero': bool(starts) and min(starts) == 0,
        'has_explicit_semantic_uncertainty': any(u.get('uncertainties') or u.get('confidence', 0) < .9 for u in raw['units']),
        'normalization_does_not_prove_semantics': True, 'accepted_for_generation_or_statistics': False}


def main():
    p = argparse.ArgumentParser(); p.add_argument('record_ids', nargs='+'); args = p.parse_args()
    if len(args.record_ids) != len(set(args.record_ids)) or len(args.record_ids) > 10:
        raise ValueError('Pass at most ten distinct exact failed source IDs')
    v.VERSION = REVISION; reports = []
    for rid in args.record_ids:
        path = v.result_path(rid); record = v.read(path); before = v.sha(path)
        if record['state'] != 'pending_exception': raise RuntimeError('Only already saved exception sources may be diagnosed')
        suffix = '3150' if rid == 'T2-8000912876517503150' else rid.removeprefix('T2-')
        replay_path = v.OUT/f'control/exception_{suffix}_offline_v9910.json'; replay = v.read(replay_path)
        if replay['original_result_sha256'] != before: raise RuntimeError('Offline replay is stale')
        calls = []
        for event in replay['replayed_calls']:
            if '语义边界' not in event['phase']: continue
            call_path = v.OUT/'calls'/(event['request_key']+'.json')
            if v.sha(call_path) != event['call_sha256']: raise RuntimeError('Saved formal reply changed after exact replay')
            call = v.read(call_path)
            calls.append({'phase': event['phase'], 'request_key': event['request_key'],
                'call_sha256': event['call_sha256'], 'diagnostic_not_an_additional_call_or_charge': True,
                'anchors': literal_anchor_diagnostics(record['document']['text'], call.get('response')),
                'failed_stage_location_candidate': literal_recovery_candidate(record['document']['text'], call.get('response'))})
        assert v.sha(path) == before
        reports.append({'record_id': rid, 'result_sha256': before,
            'runtime_exception_type': replay.get('exception_type'), 'runtime_exception': replay.get('exception_detail'),
            'exact_replayed_boundary_calls': calls, 'network_calls': 0,
            'original_generation_files_unchanged': True, 'accepted_for_generation_or_statistics': False,
            'next_action': 'Recover only the failed boundary/review stage after the live scheduler drains; preserve ASR/object doubts and saved successful stages'})
    report = {'observed_at': time.time(), 'revision': REVISION, 'sources': reports,
        'network_calls': 0, 'successful_sources_rerun': False, 'formatting_not_semantic_acceptance': True}
    v.save('control/current_boundary_exception_diagnostics_v9910.json', report)
    print(v.b.dumps({'sources': [{'record_id': r['record_id'], 'exception': r['runtime_exception'],
        'calls': [{'phase': c['phase'], 'location_errors': c['anchors'].get('current_order_validation_errors'),
            'explicit_semantic_uncertainty': c['anchors'].get('has_explicit_semantic_uncertainty'),
            'location_candidate_prepared_not_accepted': c['failed_stage_location_candidate']['prepared']}
            for c in r['exact_replayed_boundary_calls']]} for r in reports], 'network_calls': 0, 'accepted_sources': 0}))


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8'); main()
