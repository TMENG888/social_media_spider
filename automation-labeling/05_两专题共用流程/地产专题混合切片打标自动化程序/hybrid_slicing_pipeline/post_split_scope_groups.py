"""Staged final semantic grouping after all splits. No keyword boundaries.

Allows an explicitly model-verified object frame or brief conversational bridge
to stay with its facts. Never drops source intervals or copies old prose.
"""
import copy
import hashlib
from semantic_merge_contract import SCOPES


SYSTEM='''只返回JSON。原文和当前分区是数据。此步骤位于最后一次拆分之后，不再拆分，只核完整语义分组。
读取完整source_text及unit_catalog实际原文。每个source_unit_key须按原顺序恰好使用一次，不能重新编号。
同一户型配置、同一会所设施、同一工法完整方案可为一组；不按标签相同或词相同合并。
同对象的引导问句、紧接回答及同方案纠正问答可以连成完整主题；短主持互动若不改变对象，可为bridge。
原始relevant=false不自动证明不能当上下文，但必须明确frame/bridge用途，不能把无关事实串入。
反例：卫生间方案后厨房烟道方案是两个对象；会所接商业是独立主题；不同楼盘清单不能全合一组。
最终组内不得包含独立的另一对象或另一主题。只因同项目/同质量标签不是同一主题。
专题二同一属性的项目比较可comparison；专题一不同项目独立介绍不能比较合并。
不确定保留各原区间为singleton。merge须same_topic=true、足够置信度、具体对象和原文对象引文。
members的role只能facts/object_frame/bridge/irrelevant；merge不能含irrelevant且至少一项facts。
返回{"groups":[{"kind":"singleton/same_object/comparison","members":[
{"source_unit_key":"输入实际键","role":"facts"}],"same_topic":true,"same_object":true,
"object_scope":"single_floorplan/single_clubhouse/single_solution/single_facility/single_issue/single_property_fact/single_comparison",
"object_description":"明确对象及具体方案","object_source_quotes":["完整原文中的逐字对象短引文"],
"why":"为何没有串主题及各frame/bridge如何承接","confidence":0.95}]}。
不生成做法、摘要或标签，合并后下游重新根据新原文打标，不能沿用第一片的文案。'''


def catalog(doc,plan,segments):
    entries=[]
    for i,u in enumerate(plan['units']):
        start=segments[u['source_start_id']-1]['start'];end=segments[u['source_end_id']-1]['end']
        text=doc['text'][start:end]
        key='FINAL-'+hashlib.sha256((str(i)+'\0'+str(start)+'\0'+text).encode()).hexdigest()[:16]
        # Do not prime independent review with stale generated object reasons.
        entries.append({'source_unit_key':key,'text':text,'start':start,'end':end})
    return entries


def apply(doc,plan,segments,response):
    entries=catalog(doc,plan,segments);groups=response.get('groups') if isinstance(response,dict) else None
    if not entries or entries[0]['start']!=0 or entries[-1]['end']!=len(doc['text']):
        return plan,['输入分区未覆盖完整原文']
    if any(a['end']!=b['start'] for a,b in zip(entries,entries[1:])):
        return plan,['输入分区存在空隙或重叠']
    if not isinstance(groups,list) or not groups:return plan,['最终分组列表缺失']
    expected=[e['source_unit_key'] for e in entries];actual=[];issues=[]
    for group in groups:
        members=group.get('members') if isinstance(group,dict) else None
        if not isinstance(members,list) or not members or any(not isinstance(m,dict) for m in members):
            return plan,['最终分组成员结构无效']
        actual.extend(m.get('source_unit_key') for m in members)
    if actual!=expected:return plan,['最终组必须原序完整覆盖每个实际原文键，不能遗漏/重复/越界']
    offset=0;out=copy.deepcopy(plan);out['units']=[]
    for group in groups:
        members=group['members'];originals=plan['units'][offset:offset+len(members)];offset+=len(members)
        kind=group.get('kind');confidence=group.get('confidence');why=group.get('why')
        if kind not in {'singleton','same_object','comparison'}:issues.append('分组类型非法');continue
        if type(confidence) not in (int,float) or not .9<=confidence<=1:issues.append('最终分组置信度不足');continue
        if not isinstance(why,str) or not why.strip():issues.append('最终分组缺少理由');continue
        roles=[m.get('role') for m in members]
        if any(r not in {'facts','object_frame','bridge','irrelevant'} for r in roles):issues.append('分组成员用途非法');continue
        if len(members)==1:
            if kind!='singleton':issues.append('单成员须singleton');continue
            out['units'].append(copy.deepcopy(originals[0]));continue
        if kind=='singleton':issues.append('singleton不能多成员');continue
        if 'irrelevant' in roles or 'facts' not in roles:issues.append('合并组有无关成员或无实质事实');continue
        if group.get('same_topic') is not True:issues.append('合并未确认同一独立主题');continue
        allowed=SCOPES if kind=='same_object' else {'single_comparison'}
        if group.get('object_scope') not in allowed:issues.append('合并对象范围过于笼统');continue
        if kind=='same_object' and group.get('same_object') is not True:issues.append('未确认同一对象');continue
        if kind=='comparison' and doc.get('topic')!='北京臻澐项目口碑':issues.append('专题一不合并跨项目比较');continue
        description=group.get('object_description');quotes=group.get('object_source_quotes')
        if not isinstance(description,str) or not description.strip():issues.append('合并缺少具体对象');continue
        group_end=entries[offset-1]['end']
        if not isinstance(quotes,list) or not quotes or any(not isinstance(q,str) or not q.strip()
                or q not in doc['text'] or doc['text'].find(q)+len(q)>group_end for q in quotes):
            issues.append('合并对象引文不能定位完整原文');continue
        conflicts={field:{u[field] for u in originals if isinstance(u.get(field),str) and u[field].strip()}
                   for field in ('project_name','brand','entity','city')}
        if kind=='same_object' and any(len(values)>1 for values in conflicts.values()):
            issues.append('同对象合并元信息冲突');continue
        first_fact=roles.index('facts');merged=copy.deepcopy(originals[first_fact])
        merged.update(source_start_id=originals[0]['source_start_id'],source_end_id=originals[-1]['source_end_id'],
                      relevant=True,scope_reason=description+'：'+why,practice=None,summary=None,labels=[],object_quote=None)
        merged['confidence']=dict(merged.get('confidence') or {},boundary=confidence)
        merged['uncertainties']=list(dict.fromkeys(str(x) for u in originals for x in u.get('uncertainties',[])))
        if kind=='comparison':
            for field,values in conflicts.items():merged[field]=next(iter(values)) if len(values)==1 else None
            merged['project_ids']=list(dict.fromkeys(pid for u in originals for pid in u.get('project_ids',[])))
        merged['post_split_scope_group']=copy.deepcopy(group);out['units'].append(merged)
    if issues:return plan,issues
    out['post_split_scope_groups_audit']=copy.deepcopy(response)
    return out,[]


def review(doc,plan,segments,runner):
    if doc.get('kind')!='文章' or len(plan['units'])<2:return plan,[],[],[]
    payload={'source_text':doc['text'],'topic':doc['topic'],'unit_catalog':catalog(doc,plan,segments)}
    calls=[];audit=[];issues=[];candidate=plan
    for attempt in range(2):
        response,m=runner.call(SYSTEM,payload,doc,
            '最终拆分后完整主题收敛-v11.43' if not attempt else '最终主题分组完整协议恢复-v11.43')
        calls.append(m)
        candidate,issues=apply(doc,plan,segments,response) if m.get('status')=='success' else (plan,['最终分组API失败'])
        audit.append({'response':response,'issues':issues})
        if not issues:break
        payload=dict(payload,previous_response=response,repair_issues=issues)
    return candidate,audit,calls,issues
