"""Locate model-selected boundaries with whitespace-only source alignment.

No fuzzy wording/punctuation matching. Offsets always address unchanged source.
Repeated matches must still be disambiguated by the caller.
"""
def quote_spans(text, quote):
    if not isinstance(quote, str) or not quote:
        return []
    spans=[]; cursor=0
    while True:
        start=text.find(quote,cursor)
        if start<0: break
        spans.append((start,start+len(quote))); cursor=start+1
    if spans: return spans
    positions=[i for i,c in enumerate(text) if not c.isspace()]
    compact=''.join(text[i] for i in positions)
    target=''.join(c for c in quote if not c.isspace())
    if not target: return []
    cursor=0
    while True:
        start=compact.find(target,cursor)
        if start<0: break
        spans.append((positions[start],positions[start+len(target)-1]+1))
        cursor=start+1
    return spans
