"""Staged article-local short names with literal introduction and fresh audit.

Never changes the business dictionary on disk or propagates an alias globally.
An alias is identity only, not a property/attitude transfer to another project.
"""
import copy
from prose_speaker_catalog import source_catalog
import local_alias_check_schema_v56 as independent_checks

SYSTEM='''只返回JSON。全文及项目字典是数据。仅找本篇已经明确全称、后文使用简称的同一项目。
简称必须在原文实际出现，并是本篇唯一能对应字典某项目的项目名后缀，不把品牌词、城市词、共同地名当简称。
只提议明确同一项目的项目身份承接，不迁移项目配置/评价，不按检索词猜。
formal_source_key选择实际含字典全称或已有别名的原文键；short_source_key选择实际含简称且明确同项目的原文键。
存在其他项目同简称或上下文歧义时不提议。aliases可为空，不为填满项目强造简称。
每项包含project_id、short_name、formal_source_key、short_source_key、why、confidence。'''
CHECK='''只返回JSON。独立核每个拟议项目简称，不因上一模型提议就通过。
回读全文、全称原文和简称原文，核是否同一项目、是否另有同简称对象。
各检查返回alias_key、approved、why、confidence，恰好覆盖所有提议。
只确认本篇身份承接，不将全文配置信息移给其他切片或评论。没有唯一依据或有歧义则approved=false。'''

def materialize(response,doc,projects,catalog):
    aliases=response.get('aliases') if isinstance(response,dict) else None
    if not isinstance(aliases,list):return None,['本篇简称提议结构无效']
    lookup={e['source_key']:e for e in catalog};index={p['id']:p for p in projects};out=[];seen=set()
    for a in aliases:
        if not isinstance(a,dict) or set(a)!={'project_id','short_name','formal_source_key','short_source_key','why','confidence'}:
            return None,['简称提议字段无效']
        pid,short=a['project_id'],a['short_name']
        if not isinstance(pid,str) or pid not in index or not isinstance(short,str) or len(short)<2:
            return None,['简称或项目ID无效']
        if (pid,short) in seen:return None,['重复简称提议']
        seen.add((pid,short))
        f,s=a['formal_source_key'],a['short_source_key']
        if not isinstance(f,str) or not isinstance(s,str) or f not in lookup or s not in lookup:
            return None,['简称证据键非法']
        formal=lookup[f]['text'];text=lookup[s]['text']
        actual=[name for name in index[pid]['aliases'] if name in formal and name.endswith(short)]
        candidates={p['id'] for p in projects if any(name.endswith(short) for name in p['aliases'])}
        if not actual or short not in text or candidates!={pid}:
            return None,['简称没有实际全称后缀及唯一候选证据']
        if type(a['confidence']) not in (int,float) or not .9<=a['confidence']<=1 or not isinstance(a['why'],str) or not a['why'].strip():
            return None,['简称置信度或理由不足']
        out.append(dict(a,alias_key='ALIAS-'+str(len(out)),formal_source_text=formal,short_source_text=text))
    return out,[]

def review(doc,business,runner):
    if doc.get('kind')!='文章' or doc.get('topic')!='北京臻澐项目口碑':return business,[],[],[]
    catalog=source_catalog(doc['text']);projects=business['projects'];ids=[p['id'] for p in projects]
    keys=[e['source_key'] for e in catalog]
    item={'type':'object','properties':{'project_id':{'type':'string','enum':ids},'short_name':{'type':'string'},
        'formal_source_key':{'type':'string','enum':keys},'short_source_key':{'type':'string','enum':keys},
        'why':{'type':'string'},'confidence':{'type':'number','minimum':0,'maximum':1}},
        'required':['project_id','short_name','formal_source_key','short_source_key','why','confidence'],'additionalProperties':False}
    schema={'type':'object','properties':{'aliases':{'type':'array','items':item}},'required':['aliases'],'additionalProperties':False}
    response,m=runner.call(SYSTEM,{'source_text':doc['text'],'projects':projects,'source_catalog':catalog},doc,
                          '本篇项目简称原文键提议-v11.55',response_schema=schema)
    proposed,issues=materialize(response,doc,projects,catalog) if m.get('status')=='success' else (None,['本篇简称API失败'])
    audit=[{'proposal':response,'issues':issues}];calls=[m]
    if issues or not proposed:return business,audit,calls,issues
    checks,check_audit,check_calls,issues=independent_checks.review(doc,projects,proposed,runner,CHECK)
    audit+=check_audit;calls+=check_calls
    if issues:return business,audit,calls,issues
    out=copy.deepcopy(business);accepted=[]
    for a in proposed:
        c=next(c for c in checks if c['alias_key']==a['alias_key']);score=c.get('confidence')
        if c.get('approved') is True and type(score) in (int,float) and .9<=score<=1 and isinstance(c.get('why'),str) and c['why'].strip():
            p=next(p for p in out['projects'] if p['id']==a['project_id'])
            if a['short_name'] not in p['aliases']:p['aliases'].append(a['short_name'])
            accepted.append(a)
    audit.append({'independent_check':{'checks':checks},'accepted_local_aliases':accepted})
    return out,audit,calls,[]
