"""Identify invalid merge decisions for model re-review, never set boundaries."""
import copy


def filter_valid(plan,entries,decisions):
    units=plan['units'];by_key={e['edge_key']:i for i,e in enumerate(entries)}
    valid=copy.deepcopy(decisions);issues=[]
    for key,decision in decisions.items():
        if decision.get('decision')=='keep':continue
        i=by_key[key];left,right=units[i:i+2]
        reason=None
        if left.get('relevant')!=right.get('relevant'):
            reason='合并混入不同相关性区间，须模型重判，不影响其他已有效边界'
        if decision.get('decision')=='same_object':
            for field in ('project_name','brand','entity','city'):
                values={u[field] for u in (left,right) if isinstance(u.get(field),str) and u[field].strip()}
                if len(values)>1:reason='同对象合并元信息冲突：'+field
        if reason:
            valid.pop(key,None);issues.append({'edge_key':key,'reason':reason})
    # A partial catalogue never bridges a missing decision. For a complete
    # consecutive merge chain, differing themes require fresh semantic review.
    chain=[]
    def check_chain():
        if len({e['theme'] for _,e in chain})>1:
            for key,_ in chain:
                valid.pop(key,None);issues.append({'edge_key':key,'reason':'传递合并串联不同主题，须重判整条相关边界链'})
    for entry in entries:
        key=entry['edge_key'];decision=valid.get(key)
        if decision is None or decision.get('decision')=='keep':
            check_chain();chain=[]
        else:chain.append((key,decision))
    check_chain()
    return valid,issues
