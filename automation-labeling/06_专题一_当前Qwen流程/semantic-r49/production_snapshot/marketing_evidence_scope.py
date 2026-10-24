"""Remove invitation phrases, never discard an entire mixed factual clause.

This is only the lexical hard-contradiction guard's view. Original excerpts and
quotes remain untouched, and positive eligibility still requires semantic review.
"""


def factual_scope(text, invitation_pattern):
    return invitation_pattern.sub('', text)
