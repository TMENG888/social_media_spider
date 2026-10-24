"""Keep returned boundary plan and literal segment list transactionally aligned."""
import delivery_v72 as current

VERSION = 'delivery-v11.73-aligned-boundary-plan-and-source-segments-20261010'
pipeline = current.pipeline


def aligned(text, plan, segments):
    if not isinstance(plan, dict) or not segments or not plan.get('units'):
        return False
    if ''.join(s['text'] for s in segments) != text:
        return False
    if segments[0]['start'] != 0 or segments[-1]['end'] != len(text):
        return False
    if any(a['end'] != b['start'] for a, b in zip(segments, segments[1:])):
        return False
    cursor = 0
    for u in plan['units']:
        first, last = u.get('source_start_id'), u.get('source_end_id')
        if type(first) is not int or type(last) is not int or not 1 <= first <= last <= len(segments):
            return False
        if segments[first-1]['start'] != cursor:
            return False
        cursor = segments[last-1]['end']
    return cursor == len(text)


def final_scope_review(doc, plan, segments, runner):
    original = list(segments)
    out, new_segments, audit, calls, issues = pipeline.final_boundary.review(
        doc, plan, segments, runner, pipeline._quote_partition)
    if aligned(doc['text'], out, new_segments):
        # Semantic uncertainty remains in issues/audit. Literal alignment is a
        # separate invariant: a valid returned plan must use its own segments.
        segments[:] = new_segments
        return out, audit, calls, issues
    segments[:] = original
    return plan, audit, calls, issues + ['返回切片方案与原文定位列表不一致，未采用不完整分区']


def activate():
    current.activate()
    pipeline.previous.final_scope_groups.review = final_scope_review
    pipeline.previous.VERSION = VERSION
    pipeline.previous.IMPLEMENTATION_FILES = list(dict.fromkeys(
        pipeline.previous.IMPLEMENTATION_FILES + ['delivery_v73.py']))


if __name__ == '__main__':
    activate()
    pipeline.previous.main()
