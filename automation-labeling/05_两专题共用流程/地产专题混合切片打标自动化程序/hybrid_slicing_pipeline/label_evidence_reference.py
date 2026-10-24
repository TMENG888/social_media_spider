"""Program-owned literal evidence references, not article slice boundaries."""
import re

def evidence_catalog(text):
    spans=[]; start=0
    # Speaker switches are evidence anchors, not new comment output rows.
    cuts={m.end() for m in re.finditer(r'[。！？!?；;\n]',text)}
    cuts.update(m.start() for m in re.finditer(r'【(?:父评论|子评论)',text))
    cuts.add(len(text))
    for end in sorted(cuts):
        if end>start:
            spans.append({'evidence_id':len(spans)+1,'start':start,'end':end,'text':text[start:end]})
        start=end
    return spans

def resolve_evidence_ids(ids,catalog):
    if not isinstance(ids,list) or not ids or any(type(i) is not int for i in ids):return None
    if len(ids)!=len(set(ids)):return None
    lookup={s['evidence_id']:s for s in catalog}
    if any(i not in lookup for i in ids):return None
    return '...'.join(lookup[i]['text'] for i in sorted(ids))
