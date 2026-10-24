"""Keep uncertain or invalid-evidence decisions available to independent review.

These are proposals only, never accepted delivery labels. The dictionary key,
definition and evidence checks remain mandatory in the final verifier.
"""
import copy
import re
from definition_rejection_guard import added_requirement_reason


def review_candidates(audit, legal_keys):
    candidates={c['choice_key']:copy.deepcopy(c) for c in audit.get('supported',[])
                if isinstance(c,dict) and isinstance(c.get('choice_key'),str) and c.get('choice_key') in legal_keys}
    raw=audit.get('response') or {}
    decisions=raw.get('decisions') if isinstance(raw,dict) else None
    for decision in decisions if isinstance(decisions,list) else []:
        if not isinstance(decision,dict):continue
        key=decision.get('choice_key')
        if not isinstance(key,str) or key not in legal_keys or key not in audit.get('expected_keys',[]):continue
        status=decision.get('status')
        invalid_redundancy=status=='unsupported' and bool(re.search(
            r'已.{0,40}(?:覆盖|包含)|通常不重复打标|不单独(?:打标|标注)|避免碎片|优先输出核心态度',str(decision.get('why') or '')))
        invalid_requirement=status=='unsupported' and added_requirement_reason(decision.get('why'))
        if (status in {'supported','ambiguous'} or invalid_redundancy or invalid_requirement) and key not in candidates:
            candidates[key]=dict(copy.deepcopy(decision),candidate_status=status,
                routing_reason='需要独立定义/原文核验；其他标签已覆盖不证明本标签不同事实不支持')
    return candidates


def resolved_ambiguity_keys(checks):
    resolved=set()
    for check in checks if isinstance(checks,list) else []:
        if not isinstance(check,dict):continue
        confidence=check.get('confidence')
        if (isinstance(check.get('choice_key'),str) and check.get('status')=='unsupported' and isinstance(check.get('why'),str) and check['why'].strip()
                and type(confidence) in (int,float) and .9<=confidence<=1):
            resolved.add(check.get('choice_key'))
    return resolved
