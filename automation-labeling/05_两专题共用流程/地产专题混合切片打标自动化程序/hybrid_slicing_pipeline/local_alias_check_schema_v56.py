"""Independent alias checks with required response structure and bounded repair.

No silent results->checks rename, no semantic rejection retry for agreement.
"""
import copy

def validate(response,required):
    if not isinstance(response,dict) or set(response)!={'checks'}:return None,['必须仅返回checks，不重命名其他字段']
    checks=response['checks']
    if not isinstance(checks,list) or len(checks)!=len(required):return None,['简称核查未覆盖全部提议']
    if any(not isinstance(c,dict) or set(c)!={'alias_key','approved','why','confidence'} for c in checks):
        return None,['简称核查字段不完整']
    if any(not isinstance(c['alias_key'],str) for c in checks) or {c['alias_key'] for c in checks}!=set(required):
        return None,['简称核查键未知、重复或缺失']
    for c in checks:
        if type(c['approved']) is not bool or not isinstance(c['why'],str) or not c['why'].strip():return None,['简称语义决定/理由无效']
        if type(c['confidence']) not in (int,float) or not 0<=c['confidence']<=1:return None,['简称置信度无效']
    return copy.deepcopy(checks),[]

def review(doc,projects,proposed,runner,system):
    required=[a['alias_key'] for a in proposed]
    item={'type':'object','properties':{'alias_key':{'type':'string','enum':required},'approved':{'type':'boolean'},
        'why':{'type':'string'},'confidence':{'type':'number','minimum':0,'maximum':1}},
        'required':['alias_key','approved','why','confidence'],'additionalProperties':False}
    schema={'type':'object','properties':{'checks':{'type':'array','items':item,'minItems':len(required),'maxItems':len(required)}},
            'required':['checks'],'additionalProperties':False}
    payload={'source_text':doc['text'],'projects':projects,'proposed_aliases':proposed}
    audit=[];calls=[];issues=[]
    for attempt in range(2):
        response,m=runner.call(system+'\n唯一顶层字段checks，数组恰好覆盖实际alias_key；approved为布尔，confidence为0至1，不省略。不确定或不支持返回false。',
            payload,doc,'本篇简称结构化独立身份核验-v11.56' if not attempt else '本篇简称真实格式修复-v11.56',response_schema=schema)
        calls.append(m)
        checks,issues=validate(response,required) if m.get('status')=='success' else (None,['简称核查API失败'])
        audit.append({'raw_response':copy.deepcopy(response),'issues':issues})
        if not issues:return checks,audit,calls,[]
        # Only structural repair; valid approved=false never causes another call.
        payload=dict(payload,previous_response=response,repair_issues=issues)
    return None,audit,calls,issues
