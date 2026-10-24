"""Staged bounded repair of actual structured-output violations, not rejection.

Gateway JSON schema is a request, not proof of enforcement. Validate the reason
length even on a semantic rejection before treating it as a final decision.
"""
import copy
import shared_mechanism_evidence_v57 as previous
from structured_response_validation_v58 import issues as schema_issues

def protocol_issues(response,entries,members):
    complete=schema_issues(response,previous.schema(entries,members))
    if complete:return complete
    if not isinstance(response,dict) or set(response)!=set(previous.schema(entries,members)['properties']):return ['机制证明字段未恰好覆盖所请求结构']
    issues=[]
    for key in ('same_specific_system','later_restates_affirmed_mechanism','has_intervening_independent_object'):
        if type(response[key]) is not bool:issues.append(key+'须为真正布尔值')
    why=response['why']
    if not isinstance(why,str) or not 1<=len(why.strip())<=240:issues.append('why违反请求结构：必须1至240字最终理由，不含内部反思或废弃答案')
    records=response['member_assertions'];keys={e['source_unit_key'] for e in members}
    if not isinstance(records,dict) or set(records)!=keys:issues.append('逐成员结构未恰好覆盖真实键')
    return issues

def review(doc,entries,a,b,runner,validator):
    members=entries[a:b+1];payload={'source_text':doc['text'],'unit_catalog':entries,'group_members':members}
    audit=[];calls=[];candidate=None;issues=[]
    for attempt in range(2):
        response,m=runner.call(previous.SYSTEM,payload,doc,
            '逐字共同肯定机制结构核验-v11.58' if not attempt else '机制证明实际结构违规有界恢复-v11.58',
            response_schema=previous.schema(entries,members))
        calls.append(m)
        if m.get('status')!='success':
            issues=['机制证明API失败'];audit.append({'raw_mechanism_proof':copy.deepcopy(response),'issues':issues,'accepted':False});break
        structure=protocol_issues(response,entries,members)
        if structure:
            audit.append({'raw_mechanism_proof':copy.deepcopy(response),'protocol_issues':structure,'accepted':False})
            issues=structure
            payload=dict(payload,previous_response=response,protocol_issues=structure,
                repair_instruction='前次响应违反实际所请求结构，非合格语义决定。重新独立读原文，只输出最终JSON和240字内理由；各布尔字段须与最终理由一致。不要求批准：有独立系统或无共同机制应如实拒绝；不要在理由写废弃判断或思考过程。')
            continue
        candidate,issues=previous.decision(response,entries,members)
        if candidate:issues+=validator(candidate)
        audit.append({'raw_mechanism_proof':copy.deepcopy(response),'issues':issues,'accepted':not issues,
            'semantic_rejection':candidate is None,'protocol_attempt':attempt})
        # A structurally valid rejection/low confidence is final, not retried.
        return (candidate if not issues else None),audit,calls,issues
    return None,audit,calls,issues
