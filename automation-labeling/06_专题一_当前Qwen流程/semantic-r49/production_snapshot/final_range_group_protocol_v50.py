"""Staged source-only range proposals plus independent bounded group audit."""
import copy
import final_range_group_protocol_v46 as previous
import final_boundary_closure_v47 as closing
import source_only_group_recovery_v50 as recovery
import semantic_subgroups_v52 as subgroups
from complete_solution_fewshots_v52 import INSTRUCTION as COMPLETENESS

apply=previous.apply
expand=previous.expand


def review(doc,plan,segments,runner):
    if doc.get('kind')!='文章' or len(plan['units'])<2:return plan,[],[],[]
    entries=previous.previous.previous.grouping.catalog(doc,plan,segments)
    payload={'source_text':doc['text'],'topic':doc['topic'],'unit_catalog':entries,
             'ordered_source_keys':[e['source_unit_key'] for e in entries]}
    calls=[];audit=[];errors=[]
    for attempt in range(2):
        response,m=runner.call(previous.SYSTEM+recovery.INSTRUCTION+COMPLETENESS,payload,doc,
            '最终全文范围提议-v11.50' if not attempt else '最终范围提议协议恢复-v11.50')
        calls.append(m)
        _,errors=apply(doc,plan,segments,response) if m.get('status')=='success' else (plan,['全文范围提议API失败'])
        audit.append({'proposal':response,'issues':errors})
        if not errors:break
        payload=dict(payload,previous_response=response,repair_issues=errors)
    if errors:return plan,audit,calls,errors
    positions={e['source_unit_key']:i for i,e in enumerate(entries)};groups=[]
    for proposal in response['groups']:
        a=positions[proposal['start_key']];b=positions[proposal['end_key']]
        if a==b:groups.append(copy.deepcopy(proposal));continue
        validator=recovery.partition_validator(doc,plan,segments,entries,a,b,apply)
        checked,records,used,issues=recovery.review(doc,entries,a,b,runner,closing.GROUP_SYSTEM,
            validator,phase='连续范围独立整组与主题轴核查-v11.50')
        calls+=used;audit.append({'range':[a,b],'independent_group_checks':records,'issues':issues})
        if checked:groups.append(dict(checked,start_key=proposal['start_key'],end_key=proposal['end_key']))
        else:
            smaller,checks,used,subissues=subgroups.review(doc,plan,segments,entries,a,b,runner,closing.GROUP_SYSTEM,apply,records)
            groups+=smaller;calls+=used;audit.append({'subgroup_checks':checks,'issues':subissues})
    out,errors=apply(doc,plan,segments,{'groups':groups})
    return out,audit,calls,errors
