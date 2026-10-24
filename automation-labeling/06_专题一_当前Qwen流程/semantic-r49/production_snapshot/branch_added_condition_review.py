"""Staged bounded branch recheck for suspected dictionary-added requirements.

Only returns re-reviewed candidates; final independent acceptance still applies.
The original branch response is preserved. No dictionary or source is changed.
"""
import copy
import math
import audit_local_coverage_v9 as branch
import definition_alternative_conditions as alternatives
import label_definition_precision as precision


def leads(audit,index):
    response=audit.get('response')
    decisions=response.get('decisions',[]) if isinstance(response,dict) else []
    return {d['choice_key']:alternatives.review_reasons(d.get('why'),index[d['choice_key']])
            for d in decisions if isinstance(d,dict) and d.get('choice_key') in index
            and d.get('status') in {'unsupported','ambiguous'}
            and alternatives.review_reasons(d.get('why'),index[d['choice_key']])}


def validate(response,required,case,index):
    decisions=response.get('decisions') if isinstance(response,dict) else None
    if (not isinstance(decisions,list) or len(decisions)!=len(required)
            or any(not isinstance(d,dict) or not isinstance(d.get('choice_key'),str) for d in decisions)
            or {d['choice_key'] for d in decisions}!=set(required)):
        return [],['字典备选条件复核未唯一覆盖待核标签']
    issues=[]
    for d in decisions:
        confidence=d.get('confidence');why=d.get('why')
        if (d.get('status') not in {'supported','unsupported','ambiguous'}
                or not isinstance(why,str) or not why.strip()
                or type(confidence) not in (int,float) or not math.isfinite(confidence)
                or not .9<=confidence<=1):
            issues.append('定义重核决定/理由/置信度无效：'+d['choice_key']);continue
        if d['status']=='supported':
            if branch.p.quote_fragments(d.get('direct_quote'),case['child']['excerpt']) is None:
                issues.append('定义重核支持证据未逐字定位：'+d['choice_key'])
            if d.get('object_quote') and branch.p.quote_fragments(d['object_quote'],case['context']+case['child']['excerpt']) is None:
                issues.append('定义重核对象证据未定位：'+d['choice_key'])
    return decisions,issues


def review(audit,case,index,runner):
    required=leads(audit,index)
    if not required:return audit,[],[]
    payload={'slice_text':case['child']['excerpt'],'object_context':case['context'],
             'label_catalog':[{'choice_key':k,'标签强调方向':index[k]['emphasis'],
                 '打标说明':index[k]['instruction'],'标签对象路径':precision.path(index[k])} for k in sorted(required)],
             'required_keys':sorted(required),'suspected_added_requirements':required,
             'instruction':'重新按原文及字典独立判断；线索不是支持标签的证据，不照抄原决定。'}
    calls=[];attempts=[];issues=[];fixed=[]
    for attempt in range(2):
        response,m=runner.call(branch.SYSTEM+precision.INSTRUCTION+alternatives.INSTRUCTION,
            payload,case['document'],'分支备选定义条件独立反查-v11.43' if not attempt else '分支定义反查有界协议恢复-v11.43')
        calls.append(m)
        fixed,issues=validate(response,required,case,index) if m.get('status')=='success' else ([],['分支定义反查API失败'])
        attempts.append({'response':response,'issues':issues})
        if not issues:break
        payload=dict(payload,previous_response=response,repair_issues=issues)
    out=copy.deepcopy(audit)
    out['added_condition_review']={'original_response':copy.deepcopy(audit.get('response')),
                                   'leads':required,'attempts':attempts,'issues':issues}
    if issues:return out,calls,issues
    for d in fixed:
        if d['status']=='unsupported' and alternatives.review_reasons(d.get('why'),index[d['choice_key']]):
            d['original_status']='unsupported';d['status']='ambiguous'
            d['why']='反查仍疑似附加定义条件，待人工核：'+d['why']
    out['response']['decisions']=[d for d in out['response']['decisions'] if d.get('choice_key') not in required]+fixed
    out['supported']=[d for d in out.get('supported',[]) if d.get('choice_key') not in required]
    out['supported'] += [dict(d,tag=branch.p.base.label_json(index[d['choice_key']])) for d in fixed if d['status']=='supported']
    return out,calls,[]
