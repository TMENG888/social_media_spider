"""One bounded proposal for a rejected mixed group; independently audit subgroups.

No label IDs, keywords, lengths or generated prose set physical boundaries.
The rejected whole group is never retried here. Every original member survives.
"""
import source_only_group_recovery_v50 as recovery
from complete_solution_fewshots_v52 import INSTRUCTION as COMPLETENESS

SYSTEM='''只返回JSON。完整组已未通过独立主题核查，不要让原完整组再次获准。
只按全文及当前逐字成员提出其内部连续子组，涵盖每个成员恰好一次且保持原序。
连续同一具体对象完整方案或同一具体比较轴才可提议合并；不同主题分开。
轴数组只是待核线索，不是合并依据。不能按同标签、字数或关键词决定。
返回groups数组，各项仅含start_key、end_key，使用实际原文键。
可以全部单成员；不得重新提议原被拒的整个多成员范围。
程序会再独立核每个多成员子组，提议不等于获准。'''


def validate(response,entries,a,b):
    if not isinstance(response,dict) or set(response)!={'groups'}:
        return None,['子组提议必须仅包含groups']
    groups=response['groups'];positions={e['source_unit_key']:i for i,e in enumerate(entries)}
    if not isinstance(groups,list) or not groups:return None,['子组提议缺失']
    cursor=a;ranges=[]
    for group in groups:
        if not isinstance(group,dict) or set(group)!={'start_key','end_key'}:
            return None,['子组仅允许实际起止键']
        start=group['start_key'];end=group['end_key']
        if not isinstance(start,str) or not isinstance(end,str) or start not in positions or end not in positions:
            return None,['子组键非法']
        x,y=positions[start],positions[end]
        if x!=cursor or y<x or y>b:return None,['子组丢失、重叠、重排或越界']
        if x==a and y==b:return None,['不得重新提交已拒绝整组']
        ranges.append((x,y));cursor=y+1
    if cursor!=b+1:return None,['子组未覆盖所有实际成员']
    return ranges,[]


def review(doc,plan,segments,entries,a,b,runner,system,apply,rejection_records):
    singleton=lambda e:{'start_key':e['source_unit_key'],'end_key':e['source_unit_key'],'kind':'singleton'}
    fallback=[singleton(e) for e in entries[a:b+1]]
    # Legacy offline fakes keep their original protocol; real runners support schema.
    if b-a<2 or getattr(runner,'supports_response_schema',False) is not True:
        return fallback,[],[],[]
    keys=[e['source_unit_key'] for e in entries[a:b+1]]
    pair={'type':'object','properties':{k:{'type':'string','enum':keys} for k in ('start_key','end_key')},
          'required':['start_key','end_key'],'additionalProperties':False}
    schema={'type':'object','properties':{'groups':{'type':'array','items':pair}},
            'required':['groups'],'additionalProperties':False}
    payload={'source_text':doc['text'],'topic':doc['topic'],'group_members':entries[a:b+1],
             'previous_independent_checks':rejection_records}
    response,m=runner.call(SYSTEM+COMPLETENESS,payload,doc,'已拒混合组连续子组提议-v11.52',response_schema=schema)
    ranges,issues=validate(response,entries,a,b) if m.get('status')=='success' else (None,['子组API失败'])
    audit=[{'subgroup_proposal':response,'issues':issues}];calls=[m]
    if issues:return fallback,audit,calls,issues
    out=[]
    for x,y in ranges:
        if x==y:out.append(singleton(entries[x]));continue
        validator=recovery.partition_validator(doc,plan,segments,entries,x,y,apply)
        checked,records,used,errors=recovery.review(doc,entries,x,y,runner,system,validator,
            phase='连续子组独立完整主题核验-v11.52')
        audit.append({'subgroup_range':[x,y],'independent_checks':records,'issues':errors});calls+=used
        if checked:out.append(dict(checked,start_key=entries[x]['source_unit_key'],end_key=entries[y]['source_unit_key']))
        else:out.extend(singleton(e) for e in entries[x:y+1])
    return out,audit,calls,[]
