"""Attach literal header attribution to prose-audit evidence, without guessing roles.

Keep integer evidence IDs used by the verifier. Opaque source keys and speaker
metadata are additional grounding aids, not semantic approval.
"""
from focused_summary_references import catalog


def source_catalog(source):
    return catalog(str(source or ''))
