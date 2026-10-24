"""Independent full-dictionary recall pass without candidate gating."""
import delivery_v63 as current
import full_dictionary_coverage_v64 as coverage

VERSION = 'delivery-v11.64-independent-full-dictionary-fact-coverage-20261010'
pipeline = current.pipeline
_selection = pipeline.selection.review


def selection_review(text, index, context, doc, runner):
    first, calls, audit, errors = _selection(text, index, context, doc, runner)
    added, cc, aa, ee = coverage.review(text, index, context, first, doc, runner)
    merged = {tag['choice_key']: tag for tag in first}
    for tag in added:
        merged.setdefault(tag['choice_key'], tag)
    # These are proposals only: original check_unit independently binds the union.
    return list(merged.values()), calls+cc, audit+aa, errors+ee


def activate():
    current.activate()
    coverage.bounded = current.current.current.current.visible.review
    pipeline.selection.review = selection_review
    pipeline.previous.VERSION = VERSION
    pipeline.previous.IMPLEMENTATION_FILES = list(dict.fromkeys(
        pipeline.previous.IMPLEMENTATION_FILES + ['delivery_v64.py','full_dictionary_coverage_v64.py']))


if __name__ == '__main__':
    activate()
    pipeline.previous.main()
