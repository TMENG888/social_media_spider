"""Explicit user-authorized final cohort contract; original Qwen core unchanged."""
from collections import Counter
import voc_four_projects_v101 as p

NAME='delivery_cohort_contract.json'


def targets():
    file=p.OUT/NAME
    if not file.exists():return dict(p.TARGETS)
    contract=p.read(file)
    result=contract['target_counts']
    if contract.get('ratio_adjustment_authorized') is not True or set(result)!={'文章','评论'}:
        raise ValueError('Explicit ratio-adjustment contract required')
    if any(type(n) is not int or n<=0 for n in result.values()) or sum(result.values())!=1000:
        raise ValueError('Exactly 1000 real article/comment sources required')
    return dict(result)


def preserved_cohort(records):
    file=p.OUT/NAME
    if not file.exists():return
    contract=p.read(file);index={record['record_id']:record for record in records}
    for rid,digest in contract['retained_result_sha256'].items():
        if rid not in index or p.v.sha(p.path_for('results',rid))!=digest:
            raise ValueError('Originally successful source missing or changed: '+rid)
    if Counter(record['kind'] for record in records)!=targets():
        raise ValueError('Authorized final composition unmet')
