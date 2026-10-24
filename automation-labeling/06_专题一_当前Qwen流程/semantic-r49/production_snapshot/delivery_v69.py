"""Review an invalid proposal as evidence, never accept it as final boundaries."""
import copy
import delivery_v68 as current

VERSION = 'delivery-v11.69-boundary-review-invalid-proposal-recovery-20261010'
pipeline = current.pipeline


def boundary_call(system, payload, schema, doc, phase, runner):
    raw, calls, audit, errors = current.current.boundary_call(system, payload, schema, doc, phase, runner)
    proposal = raw
    if proposal is None and calls and all(c.get('status') == 'success' for c in calls):
        # Retain the unmodified invalid response solely for independent review.
        # API/auth failures must not be disguised as a structural recovery.
        for item in reversed(audit):
            candidate = item.get('raw_response')
            if isinstance(candidate, dict) and isinstance(candidate.get('units'), list):
                proposal = candidate
                break
    if proposal is None:
        return raw, calls, audit, errors
    request = copy.deepcopy(payload)
    request['proposed_boundaries'] = proposal
    request['proposal_protocol_issues'] = errors
    reviewed, more, checks, issues = current.current.boundary_call(
        system + current.REVIEW_NOTE, request, schema, doc,
        '完整对象边界独立审核-v11.69', runner)
    return reviewed, calls + more, audit + checks, issues


def activate():
    current.activate()
    current.current.current.current.boundaries.bounded = boundary_call
    pipeline.previous.VERSION = VERSION
    pipeline.previous.IMPLEMENTATION_FILES = list(dict.fromkeys(
        pipeline.previous.IMPLEMENTATION_FILES + ['delivery_v69.py']))


if __name__ == '__main__':
    activate()
    pipeline.previous.main()
