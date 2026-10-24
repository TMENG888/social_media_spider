"""Model-confirmed position recovery without editing semantic decisions."""
import copy
import delivery_v70 as current
import global_anchor_resolution_v71 as resolver

VERSION = 'delivery-v11.71-model-confirmed-full-source-anchor-resolution-20261010'
pipeline = current.pipeline
_review = current.boundaries.review


def review(doc, old_plan, old_segments, runner, parse_partition):
    plan, segments, audit, calls, errors = _review(doc, old_plan, old_segments, runner, parse_partition)
    if not errors:
        return plan, segments, audit, calls, errors
    if not all(issue.startswith('全文起点不能逐字定位：') for issue in errors):
        return plan, segments, audit, calls, errors
    proposal = None
    for item in reversed(audit):
        raw = item.get('raw_response')
        if isinstance(raw, dict) and isinstance(raw.get('units'), list) and raw['units']:
            proposal = raw
            break
    if proposal is None or any(c.get('status') != 'success' for c in calls):
        return plan, segments, audit, calls, errors
    resolved, ss, aa, cc, issues = resolver.review(doc['text'], proposal, doc, runner, parse_partition)
    audit += aa
    calls += cc
    if issues:
        return old_plan, old_segments, audit, calls, issues
    resolved['full_source_global_boundary_v70'] = copy.deepcopy(audit)
    resolved['model_confirmed_position_resolution_v71'] = True
    return resolved, ss, audit, calls, []


def activate():
    current.activate()
    pipeline.final_boundary.review = review
    pipeline.previous.VERSION = VERSION
    pipeline.previous.IMPLEMENTATION_FILES = list(dict.fromkeys(
        pipeline.previous.IMPLEMENTATION_FILES + ['delivery_v71.py', 'global_anchor_resolution_v71.py']))


if __name__ == '__main__':
    activate()
    pipeline.previous.main()
