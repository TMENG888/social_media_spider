"""Staged program-owned literal catalogue respecting final article boundaries.

This is reference construction, not a source slicing decision. It prevents a
long punctuation-free evidence span from looking like a future identity.
"""
import hashlib
from focused_summary_references import catalog as local_catalog


def catalog(doc,units,segments):
    entries=[];end=0
    for index,unit in enumerate(units):
        start=segments[unit['source_start_id']-1]['start'];stop=segments[unit['source_end_id']-1]['end']
        if start!=end or stop<=start or stop>len(doc['text']):
            raise ValueError('最终身份目录输入不是无损连续分区')
        for entry in local_catalog(doc['text'][start:stop]):
            global_start=start+entry['start'];global_end=start+entry['end']
            actual=doc['text'][global_start:global_end]
            if actual!=entry['text'] or global_end>stop:
                raise ValueError('身份目录证据不能定位实际原文区间')
            key='META-'+hashlib.sha256((str(global_start)+'\0'+actual).encode('utf-8')).hexdigest()[:16]
            entries.append(dict(entry,source_key=key,start=global_start,end=global_end,
                                text=actual,final_unit_index=index))
        end=stop
    if end!=len(doc['text']):raise ValueError('最终身份目录漏掉文章末尾')
    return entries
