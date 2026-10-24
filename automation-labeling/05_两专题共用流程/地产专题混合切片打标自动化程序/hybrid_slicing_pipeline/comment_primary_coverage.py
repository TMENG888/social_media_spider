"""Whole-comment coverage gate, paired with mandatory fragment entailment.

This module never approves factual correctness. Every prose fragment must pass
the separate source/object/relationship audit before a summary is accepted.
"""
from focused_summary_references import catalog
from prose_living_impact_scope import issues as living_issues
from prose_source_constraints import issues as source_issues


def verify(source, prose, response):
    coverage=response.get('coverage') if isinstance(response,dict) else None
    if not isinstance(coverage,dict):
        return False,[{'accepted':False,'reason':'完整评论主要观点覆盖决定缺失'}]
    keys=coverage.get('source_keys');entries={e['source_key']:e for e in catalog(source)}
    valid=(isinstance(keys,list) and bool(keys) and all(isinstance(k,str) and k in entries for k in keys)
           and len(keys)==len(set(keys)))
    confidence=coverage.get('confidence');why=coverage.get('why')
    passed=(bool(prose) and coverage.get('captures_primary_points') is True and valid
            and type(confidence) in (int,float) and .9<=confidence<=1
            and isinstance(why,str) and bool(why.strip()))
    audit=[dict(coverage,accepted=passed,review_type='whole_comment_primary_coverage_only',
                legacy_fragment_decisions=response.get('checks'),
                verification_scope='全文主要观点覆盖；不是片段事实验收，另须逐片原文关联审核')]
    constraints=living_issues(source,prose)+source_issues(source,prose)
    return passed and not constraints,audit+constraints
