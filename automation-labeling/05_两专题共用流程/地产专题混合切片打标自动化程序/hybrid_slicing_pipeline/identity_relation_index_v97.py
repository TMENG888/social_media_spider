"""Traceable project/entity relation candidates, never a blind brand lookup.

This module is deliberately separate from the live identity resolver. Candidate
co-occurrence is not ownership evidence. An index entry needs a separate relation
review and source geometry verification before even being offered to a target
reviewer. Target applicability still requires a same-project review.
"""
import copy
import hashlib
import json
import re

VERSION = 'v97-project-entity-relations-20261013'


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':')).encode('utf-8')).hexdigest()


def name_key(name):
    # Typography only. No abbreviation, phonetic, fuzzy or substring matching.
    return re.sub(r'[\s·•‧・]', '', name)


def spans(contexts, literal):
    found = []
    for source, text in contexts.items():
        start = 0
        while literal and (pos := text.find(literal, start)) >= 0:
            found.append({'source': source, 'start': pos, 'end': pos+len(literal),
                          'text': literal})
            start = pos+len(literal)
    return found


def valid_span(proof, contexts):
    return (isinstance(proof, dict) and proof.get('source') in contexts
            and type(proof.get('start')) is int and type(proof.get('end')) is int
            and 0 <= proof['start'] < proof['end'] <= len(contexts[proof['source']])
            and contexts[proof['source']][proof['start']:proof['end']] == proof.get('text'))


def scope_objects(resolved):
    # The resolver audit retains all model responses. Only the first successful
    # object-collection response is relevant; never interpret draft decisions as
    # a scope declaration or let a later response overwrite the objects silently.
    for event in resolved.get('audit', []):
        raw = event.get('raw_response') or {}
        if isinstance(raw.get('objects'), list) and not event.get('protocol_issues'):
            return {x['unit_id']: x for x in raw['objects'] if isinstance(x, dict)
                    and isinstance(x.get('unit_id'), str)}
    return {}


def candidate_relations(job, resolved, business):
    """Use approved entity decisions and literal residential scopes as leads.

    Existing workbook values alone are not an index source. Even accepted
    identity decisions are only leads until an independent ownership review.
    """
    entities = {e['entity']: e['brand'] for e in business.get('entities', [])}
    objects = scope_objects(resolved)
    candidates = []
    for decision in resolved.get('decisions', []):
        check = decision.get('review') or {}
        vals = decision.get('values', [])
        if (decision.get('field') != '经营主体' or len(vals) != 1 or vals[0] not in entities
                or check.get('approve') is not True or not all(check.get(k) is True for k in
                    ('same_object', 'all_objects_covered', 'residential_identity', 'no_identity_conflict'))):
            continue
        scope = objects.get(decision['unit_id']) or {}
        names = scope.get('project_names', [])
        if (not isinstance(names, list) or not names or scope.get('confidence', 0) < .9
                or len(names) != len(set(names)) or not all(isinstance(n, str) and spans(job['contexts'], n) for n in names)):
            continue
        evidence = decision.get('evidence', [])
        if not evidence or not all(valid_span(e, job['contexts']) for e in evidence):
            continue
        for name in names:
            c = {'version': VERSION, 'record_id': job['record_id'], 'job_id': job.get('job_id'),
                 'unit_id': decision['unit_id'], 'project_name': name, 'entity': vals[0],
                 'brand': entities[vals[0]], 'context_hash': digest(job['contexts']),
                 'project_evidence': spans(job['contexts'], name), 'entity_evidence': copy.deepcopy(evidence),
                 'scope': copy.deepcopy(scope), 'identity_review': copy.deepcopy(check),
                 'state': 'candidate_requires_independent_relation_review'}
            c['relation_id'] = digest({k: c[k] for k in ('record_id', 'unit_id', 'project_name', 'entity', 'context_hash')})
            candidates.append(c)
    return candidates


def verify_relation(candidate, review, contexts, business):
    """Verify reviewed relation geometry. Does not infer ownership from names."""
    issues = []
    legal = {e['entity']: e['brand'] for e in business.get('entities', [])}
    if candidate.get('context_hash') != digest(contexts): issues.append('source_hash_changed')
    if legal.get(candidate.get('entity')) != candidate.get('brand'): issues.append('entity_brand_dictionary_conflict')
    if review.get('relation_id') != candidate.get('relation_id'): issues.append('wrong_relation_target')
    if review.get('approve') is not True: issues.append('relation_not_approved')
    if review.get('relation_type') not in ('development', 'operation'): issues.append('not_development_or_operation')
    if review.get('same_project') is not True: issues.append('relation_project_not_confirmed')
    if review.get('joint_or_conflicting_entity') is not False: issues.append('joint_or_conflicting_entity')
    confidence = review.get('confidence')
    if type(confidence) not in (float, int) or not .9 <= confidence <= 1: issues.append('relation_confidence_insufficient')
    if not isinstance(review.get('why'), str) or not review['why'].strip(): issues.append('missing_relation_reason')
    proof = review.get('relation_evidence', [])
    if not proof or not all(valid_span(e, contexts) for e in proof): issues.append('invalid_relation_evidence')
    if not any(valid_span(e, contexts) and candidate.get('project_name') in e['text'] for e in proof):
        issues.append('relation_evidence_has_no_literal_project_name')
    # A relation can use a group alias already approved by the identity reviewer;
    # its original entity evidence must remain visible, not replaced by the name.
    if not candidate.get('entity_evidence') or not all(valid_span(e, contexts) for e in candidate['entity_evidence']):
        issues.append('invalid_original_entity_evidence')
    city = review.get('city')
    city_proof = review.get('city_evidence', [])
    if city is not None and (not isinstance(city, str) or not city.strip()
            or not city_proof or not all(valid_span(e, contexts) and city in e['text'] for e in city_proof)):
        issues.append('invalid_city_evidence')
    return issues


def publish(candidate, review, contexts, business):
    issues = verify_relation(candidate, review, contexts, business)
    if issues: raise ValueError(','.join(issues))
    return dict(copy.deepcopy(candidate), relation_review=copy.deepcopy(review),
                state='relation_verified_target_applicability_still_requires_review')


def relation_leads(project_name, record_id, city, index):
    """Offer exact-name verified leads; never write a cell automatically.

    Same-source evidence can be offered without a city. Cross-source evidence
    needs an explicit matching city, since short/same-name projects recur.
    Conflicting group relations are withheld rather than selected by majority.
    """
    found = [e for e in index if e.get('state') == 'relation_verified_target_applicability_still_requires_review'
             and name_key(e.get('project_name', '')) == name_key(project_name)
             and (e.get('record_id') == record_id or city is not None
                  and e.get('relation_review', {}).get('city') == city)]
    if len({e['entity'] for e in found}) > 1:
        return {'leads': [], 'stop_reason': 'conflicting_verified_project_entities'}
    return {'leads': copy.deepcopy(found), 'stop_reason': None if found else 'no_exact_project_city_relation'}
