"""Recover only explicit unique dictionary aliases in current slice/context.

No research-keyword or whole-parent inheritance. Ambiguous aliases are deferred.
This recovers identity, not per-tag target or sentiment and not auto-acceptance.
"""
import copy

def recover(unit,projects):
    out=copy.deepcopy(unit)
    scope=(out.get('_excerpt') or '')+' '+(out.get('object_quote') or '')
    hits={}; ambiguity=[]
    by_alias={}
    for project in projects:
        for alias in project.get('aliases') or []:
            if alias:by_alias.setdefault(alias,[]).append(project)
    for alias, matches in by_alias.items():
        if alias not in scope:continue
        ids={p['id'] for p in matches}
        if len(ids)!=1:ambiguity.append(alias);continue
        project=matches[0]
        previous=hits.get(project['id'])
        if previous is None or len(alias)>len(previous['evidence']):
            hits[project['id']]={'id':project['id'],'evidence':alias,
                'why':'当前切片/有据对象上下文明示唯一项目别名，程序按字典恢复身份，不补配置或态度'}
    previous=set(out.get('project_ids') or [])
    added=set(hits)-previous
    if added:
        out['project_ids']=list(dict.fromkeys(list(out.get('project_ids') or [])+list(hits)))
        out['project_evidence']=[e for e in out.get('project_evidence') or [] if e.get('id') not in added]+[hits[p] for p in hits if p in added]
        out.setdefault('uncertainties',[]).append('已按当前原文项目名恢复身份；多项目逐标签归属仍需审核：'+','.join(sorted(added)))
    if ambiguity:out.setdefault('uncertainties',[]).append('项目别名不唯一，未强制关联：'+','.join(sorted(set(ambiguity))))
    return out
