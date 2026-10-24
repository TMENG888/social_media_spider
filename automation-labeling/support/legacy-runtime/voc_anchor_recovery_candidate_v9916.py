"""Offline candidate only: reuse reviewed literal locator before schema checks.

No production launcher imports this module. Model-selected starts only; never
invent, merge, split or semantically approve units. Existing independent boundary
review and all annotation gates must remain in place when integrated later.
"""
import copy
from collections import Counter
import voc_batch_v99 as v
from inspect_boundary_exceptions_v9910 import literal_recovery_candidate
from structured_response_validation_v58 import issues
from bounded_visible_contract_v60 import contract


def semantics(raw):
    return Counter(v.b.dumps({k:val for k,val in unit.items()
                             if k not in {'start_quote','start_occurrence'}})
                   for unit in raw['units'])


def candidate(text, raw):
    original=copy.deepcopy(raw)
    if isinstance(raw,dict) and isinstance(raw.get('units'),list):
        schema_errors=issues(raw,contract(v.partition.boundary.SCHEMA,{}))
        _,location_errors=v.partition.boundary.locate(text,raw)
        if not schema_errors and not location_errors:
            return original,{'prepared':False,'reason':'Original location/schema already valid; preserve exact cache inputs',
                             'not_accepted_for_generation_or_statistics':True}
    proposal=literal_recovery_candidate(text,raw)
    if not proposal.get('prepared'):
        return original,{'prepared':False,'reason':proposal['reason'],
                         'not_accepted_for_generation_or_statistics':True}
    fixed=proposal['location_only_candidate']
    if (len(fixed['units'])!=len(raw['units']) or semantics(raw)!=semantics(fixed)
            or {k:val for k,val in raw.items() if k!='units'}!={k:val for k,val in fixed.items() if k!='units'}):
        raise RuntimeError('Locator changed semantic content, confidence, uncertainty or unit count')
    if raw!=original:
        raise RuntimeError('Original formal response was mutated')
    return fixed,{'prepared':True,'position_audit':proposal['position_audit'],
                  'source_lossless_segments':proposal['segments'],
                  'confidence_uncertainties_and_semantic_fields_unchanged':True,
                  'independent_semantic_review_still_required':True,
                  'not_accepted_for_generation_or_statistics':True}


def runner_class(base):
    """Integration candidate only; does not replace any live class or function."""
    class AnchorRecoveryRunner(base):
        def call(self,system,payload,doc,phase,response_schema=None):
            raw,metric=super().call(system,payload,doc,phase,response_schema)
            if raw is None or not phase.startswith('Reduce全文语义边界'):
                return raw,metric
            fixed,proof=candidate(doc['text'],raw)
            if proof['prepared'] and fixed!=raw:
                metric=dict(metric,source_owned_location_recovery_v9916=proof)
                return fixed,metric
            return raw,metric
    return AnchorRecoveryRunner
