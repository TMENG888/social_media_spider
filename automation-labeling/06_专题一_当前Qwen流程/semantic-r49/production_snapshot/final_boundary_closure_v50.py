"""Staged per-boundary closure with group-local real protocol recovery."""
from concurrent.futures import ThreadPoolExecutor
import final_boundary_closure_v47 as previous
import source_only_group_recovery_v50 as recovery
import semantic_subgroups_v52 as subgroups
from complete_solution_fewshots_v52 import INSTRUCTION as COMPLETENESS

edge_decision=previous.edge_decision
chains=previous.chains


def review(doc,plan,segments,runner):
    if doc.get('kind')!='文章' or len(plan['units'])<2:return plan,[],[],[]
    ranges=previous.ranges
    entries=ranges.previous.previous.grouping.catalog(doc,plan,segments)
    audit=[];calls=[];decisions={};errors=[]
    def inspect_edge(i):
        key='CLOSE-'+entries[i]['source_unit_key']+'-'+entries[i+1]['source_unit_key']
        payload={'source_text':doc['text'],'edge_key':key,'left':entries[i],'right':entries[i+1],
                 'topic':doc['topic'],'preceding_neighbor':entries[i-1] if i else None,
                 'following_neighbor':entries[i+2] if i+2<len(entries) else None}
        response,m=runner.call(previous.EDGE_SYSTEM+COMPLETENESS+'\n不同具体比较维度必须keep；整体项目对比不是单一比较维度，开发品牌、价格、定位、户型、精装、园林、会所为不同主题。',payload,doc,'最终相邻边界全文核查-v11.52')
        decision=edge_decision(response,key,doc['topic']) if m.get('status')=='success' else None
        return i,decision,m,{'edge_key':key,'response':response,'valid_decision':decision is not None}
    with ThreadPoolExecutor(max_workers=10) as pool:
        for i,decision,m,record in pool.map(inspect_edge,range(len(entries)-1)):
            calls.append(m);audit.append(record)
            if decision:decisions[i]=decision
            else:errors.append('边界'+str(i)+'未完成独立语义核验，保留原边界')
    groups=[]
    for a,b in chains(decisions,len(entries)):
        if a==b:
            groups.append({'start_key':entries[a]['source_unit_key'],'end_key':entries[b]['source_unit_key'],'kind':'singleton'})
            continue
        validator=recovery.partition_validator(doc,plan,segments,entries,a,b,ranges.apply)
        checked,records,used,issues=recovery.review(doc,entries,a,b,runner,previous.GROUP_SYSTEM,
            validator,phase='相邻链独立整组与主题轴核查-v11.50')
        calls+=used;audit.append({'proposed_range':[a,b],'independent_group_checks':records,'issues':issues})
        if checked:groups.append(dict(checked,start_key=entries[a]['source_unit_key'],end_key=entries[b]['source_unit_key']))
        else:
            errors+=['相邻链'+str(a)+'-'+str(b)+'未核实：'+issue for issue in issues]
            smaller,checks,used,subissues=subgroups.review(doc,plan,segments,entries,a,b,runner,previous.GROUP_SYSTEM,ranges.apply,records)
            groups+=smaller;calls+=used;audit.append({'subgroup_checks':checks,'issues':subissues})
    out,protocol_errors=ranges.apply(doc,plan,segments,{'groups':groups})
    errors+=protocol_errors
    if protocol_errors:return plan,audit,calls,errors
    out['final_boundary_closure_audit']=audit
    return out,audit,calls,errors
