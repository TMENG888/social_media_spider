"""Required model-owned group fields. Schema compliance is not truth proof."""
from source_only_group_recovery_v50 import AXES
from semantic_merge_contract import SCOPES
import copy


def schema(entries,members):
    keys=[e['source_unit_key'] for e in members]
    roles={k:{'type':'string','enum':['facts','object_frame','bridge','irrelevant']} for k in keys}
    axes={k:{'type':'array','items':{'type':'string','enum':list(AXES)+['unknown']}} for k in keys}
    properties={
        'approved':{'type':'boolean'},'kind':{'type':['string','null'],'enum':['same_object','comparison','mixed_topics',None]},
        'same_topic':{'type':'boolean'},'same_object':{'type':'boolean'},
        'object_scope':{'type':['string','null'],'enum':sorted(SCOPES)+['single_comparison',None]},
        'object_description':{'type':['string','null']},
        'member_roles':{'type':'object','properties':roles,'required':keys,'additionalProperties':False},
        'object_references':{'type':'array','items':{'type':'object','properties':{
            'source_unit_key':{'type':'string','enum':[e['source_unit_key'] for e in entries]}},
            'required':['source_unit_key'],'additionalProperties':False}},
        'comparison_axis':{'type':['string','null'],'enum':list(AXES)+[None]},
        'member_axes':{'type':'object','properties':axes,'required':keys,'additionalProperties':False},
        'why':{'type':'string'},'confidence':{'type':'number','minimum':0,'maximum':1}}
    return {'type':'object','properties':properties,'required':list(properties),'additionalProperties':False}


INSTRUCTION='''
最终JSON必须完整包含approved、kind、same_topic、same_object、object_scope、object_description、member_roles、object_references、comparison_axis、member_axes、why、confidence。
confidence必须由你评估为0到1之间的数字，不能省略，不使用固定默认信心。
同对象组comparison_axis=null，member_axes给每个实际键空数组；比较组给每个实际键真实轴数组。
不支持或不确定时approved=false，解释真实原因；仍返回全部字段，未知对象字段可null，对象证据可空数组。
新协议object_references每个对象只能包含source_unit_key，选含真实对象身份/承接证据的实际片段键。
禁止生成object_quote；程序按键原样取回该片段全文，不允许改写、拼接或省略号。原字段示例中的object_quote已由本新协议替代。
输出结构合法仅证明结构，不证明内容正确；每个语义决定仍须原文证据。
'''


def materialize(response,entries):
    if not isinstance(response,dict):return None,['组响应非对象']
    refs=response.get('object_references');lookup={e['source_unit_key']:e for e in entries}
    if not isinstance(refs,list):return None,['对象原文键列表缺失']
    out=copy.deepcopy(response);resolved=[];seen=set()
    for ref in refs:
        if not isinstance(ref,dict) or set(ref)!={'source_unit_key'}:
            return None,['新协议只允许模型选择对象原文键，禁止旧object_quote及伪引文被静默修正']
        key=ref['source_unit_key']
        if not isinstance(key,str) or key not in lookup or key in seen:
            return None,['对象键不在实际原文目录或重复']
        seen.add(key);resolved.append({'source_unit_key':key,'object_quote':lookup[key]['text']})
    out['object_references']=resolved
    return out,[]
