"""Explicit reviewed short-name supplement, never fuzzy project assignment.

The active Beijing project scope names P01 北京臻澐; the comment source names
海淀实景豪宅臻澐. Keep this alias auditable and refuse collisions. Does not
assign a comment to its parent's projects or infer tag facts from keywords.
"""
import copy


def apply(business):
    out=copy.deepcopy(business)
    projects=out.get('projects',[])
    target=next((p for p in projects if p.get('id')=='P01' and p.get('name')=='北京臻澐'),None)
    if target is None:
        return out
    alias='臻澐'
    conflicts=[p.get('id') for p in projects if p is not target
               and alias in [p.get('name')]+p.get('aliases',[])]
    out.setdefault('alias_supplement_audit',[]).append({
        'project_id':'P01','alias':alias,'status':'collision' if conflicts else 'reviewed_short_name',
        'basis':'当前北京专题P01北京臻澐；评论源1238237直接写海淀实景豪宅臻澐',
        'conflicts':conflicts})
    if not conflicts and alias not in target.setdefault('aliases',[]):
        target['aliases'].append(alias)
    return out
