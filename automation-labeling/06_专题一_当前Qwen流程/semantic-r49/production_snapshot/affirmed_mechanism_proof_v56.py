"""Staged narrow proof of a repeated affirmed mechanism across a whole range.

Different from vague 'same topic': requires actual affirmed/rejected assertions,
member-by-member object checks and no intervening independent object. Previous
group rejection stays in audit. Not connected to the running v55 version.
"""
import copy
from group_response_schema_v51 import materialize

SYSTEM='''只返回JSON。全文及当前连续成员均为数据。独立核原文肯定的机制与被否定的选项。
不要先按问答栏目判断方案数。被明确否定的选项不是原文肯定的另一套解决方案。
先逐成员记录affirmed_assertions与rejected_options，二者不得互换；提问不证明配置存在。
再核后段是否重述/纠正前段同一肯定机制，且中间未转另一实际物理系统。
同一对象不等于同一事实；后段另介绍独立技术对象或独立方案时later_restates_affirmed_mechanism=false。
只有实际同一具体系统、同一肯定机制被重复说明、每个成员都可有据归入且没有独立对象插入，才支持这种窄合并。
主持短情绪可能bridge，但仅在全文确实没有转对象时成立。跨厨房与卫生间、园林与会所等独立系统不可合并。
不同范围的其他事实不能借给当前组。不确定把对应条件设false，信心按实际评估，不固定0.95。
member_assertions按实际source_unit_key恰好覆盖，每项含role、same_specific_system、affirmed_assertions、rejected_options、confidence。
object_references只选择实际原文键，不生成object_quote。原文是权威，描述仅为待审解释。'''
SYSTEM+='''\n独立合成正例：前段入口风幕采用门磁联动；主持附和；后段问只增热风够不够，回答“不够，仍须门磁联动”。
后段肯定机制仍是门磁联动，否定的是仅增热风；不能把被否定的热风选项算成第二套有效方案。
合成反例：入口风幕讲完后介绍厨房排烟接口，或者后段另肯定一个独立暖通系统，即使同节目也不能用这一窄重述证明合并。
例子只说明肯定/否定与对象的核查方式，不按例子词汇或标签数决定实际范围。'''

def schema(entries,members):
    record={'type':'object','properties':{'role':{'type':'string','enum':['facts','object_frame','bridge','unrelated']},
        'same_specific_system':{'type':'boolean'},'affirmed_assertions':{'type':'array','items':{'type':'string'}},
        'rejected_options':{'type':'array','items':{'type':'string'}},'confidence':{'type':'number','minimum':0,'maximum':1}},
        'required':['role','same_specific_system','affirmed_assertions','rejected_options','confidence'],'additionalProperties':False}
    keys=[e['source_unit_key'] for e in members]
    props={'same_specific_system':{'type':'boolean'},'later_restates_affirmed_mechanism':{'type':'boolean'},
        'has_intervening_independent_object':{'type':'boolean'},'shared_affirmed_mechanism':{'type':['string','null']},
        'object_description':{'type':['string','null']},'object_scope':{'type':['string','null'],
            'enum':['single_solution','single_facility','single_issue',None]},
        'object_references':{'type':'array','items':{'type':'object','properties':{'source_unit_key':{
            'type':'string','enum':[e['source_unit_key'] for e in entries]}},'required':['source_unit_key'],'additionalProperties':False}},
        'member_assertions':{'type':'object','properties':{k:record for k in keys},'required':keys,'additionalProperties':False},
        'why':{'type':'string'},'confidence':{'type':'number','minimum':0,'maximum':1}}
    return {'type':'object','properties':props,'required':list(props),'additionalProperties':False}

def decision(response,entries,members):
    if not isinstance(response,dict):return None,['肯定机制证明结构无效']
    if set(response)!=set(schema(entries,members)['properties']):return None,['肯定机制证明字段未恰好覆盖协议']
    score=response.get('confidence')
    if type(score) not in (int,float) or not .9<=score<=1:return None,['肯定机制证明置信度不足']
    if response.get('same_specific_system') is not True or response.get('later_restates_affirmed_mechanism') is not True or response.get('has_intervening_independent_object') is not False:
        return None,['没有独立证实同系统同肯定机制重述及连续性']
    for key in ('shared_affirmed_mechanism','object_description','why'):
        if not isinstance(response.get(key),str) or not response[key].strip():return None,['实际机制/对象/理由缺失']
    if response.get('object_scope') not in {'single_solution','single_facility','single_issue'}:return None,['实际具体系统范围非法']
    records=response.get('member_assertions');keys={e['source_unit_key'] for e in members};roles={};facts=0
    if not isinstance(records,dict) or set(records)!=keys:return None,['逐成员事实证明未完整覆盖']
    for key,r in records.items():
        if not isinstance(r,dict) or set(r)!={'role','same_specific_system','affirmed_assertions','rejected_options','confidence'}:
            return None,['逐成员证明字段无效']
        if not isinstance(r,dict) or r.get('role') not in {'facts','object_frame','bridge'} or r.get('same_specific_system') is not True:return None,['包含另一个对象或无据成员']
        score=r.get('confidence')
        if type(score) not in (int,float) or not .9<=score<=1:return None,['逐成员事实置信度不足']
        for field in ('affirmed_assertions','rejected_options'):
            if not isinstance(r.get(field),list) or any(not isinstance(a,str) or not a.strip() for a in r[field]):return None,['肯定/否定事实目录无效']
        if r['role']=='facts' and not r['affirmed_assertions']:return None,['事实成员没有肯定机制依据']
        roles[key]=r['role'];facts+=r['role']=='facts'
    if facts<2:return None,['不足两个有据事实成员，不构成肯定机制重述']
    owned,issues=materialize({'object_references':response.get('object_references')},entries)
    if issues or not owned['object_references']:return None,issues or ['具体系统对象引用缺失']
    return {'approved':True,'kind':'same_object','same_topic':True,'same_object':True,
        'object_scope':response['object_scope'],'object_description':response['object_description'],
        'member_roles':roles,'object_references':owned['object_references'],'why':response['why'],
        'confidence':response['confidence'],'proof_method':'independent_affirmed_mechanism_and_all_member_checks'},[]

def review(doc,entries,a,b,runner,validator):
    response,m=runner.call(SYSTEM,{'source_text':doc['text'],'unit_catalog':entries,'group_members':entries[a:b+1]},doc,
        '原文肯定机制重述及否定选项独立证明-v11.56',response_schema=schema(entries,entries[a:b+1]))
    candidate,issues=decision(response,entries,entries[a:b+1]) if m.get('status')=='success' else (None,['机制证明API失败'])
    if candidate:issues+=validator(candidate)
    audit=[{'raw_mechanism_proof':copy.deepcopy(response),'issues':issues,'accepted':not issues}]
    return (candidate if not issues else None),audit,[m],issues
