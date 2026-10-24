"""Staged explicit root-object evidence within each model-proposed scope.

Projection to the existing literal-boundary contract is declared here; raw
protocol remains in audit. Root categories are model-owned, not keywords.
"""
import copy
from concurrent.futures import ThreadPoolExecutor
import physical_scope_pass_v57 as previous
from structured_response_validation_v58 import issues as schema_issues

SYSTEM=previous.SYSTEM+'''
每个scope新增root_objects数组，先按原文逐个列出实际根对象及其当前片内逐字证据，再确定是否能同片。
每项为{subject,quote,category,role}，role只选facts或context。context只允许没有独立配置的过渡。
root_objects不是把所有配置抽象成“社区公区”；庭园景观和会所空间是不同根对象，均有独立配置时必须如实列出，不能把庭园设施归会所。
同一会所下泳池与阅读区属于同一clubhouse根类；同一户型的卧室与阳台属于同一floorplan根类。
两项目同一具体维度可以一片，但片内有不同实际根类时应在对象转换处拆开；保留原位连续顺序。
合成例：甲项目庭园设环形步道，内会所设阅读和瑜伽区。分别列庭园landscape、会所clubhouse，两者都有facts证据，应原位两片。
反例：将前例仅列“甲公区，clubhouse”，没有逐对象核查；或将实际庭园称context以规避不同对象。
同一具体方案的共同肯定机制及其补充可保持solution一片。root_objects只提供结构化有据核查，不代替后续独立审核。
输出其余结构保持原协议。'''

def schema():
    out=copy.deepcopy(previous.schema());scope=out['properties']['scopes']['items']
    fields={'subject':{'type':'string','minLength':1},'quote':{'type':'string','minLength':1},
        'category':{'type':'string','enum':previous.CATEGORIES},'role':{'type':'string','enum':['facts','context']}}
    scope['properties']['root_objects']={'type':'array','minItems':1,'items':{'type':'object','properties':fields,
        'required':list(fields),'additionalProperties':False}}
    scope['required'].append('root_objects')
    return out

def apply_one(plan,segments,response):
    complete=schema_issues(response,schema())
    if complete:return plan,segments,complete
    if not isinstance(response,dict) or not isinstance(response.get('scopes'),list):return plan,segments,['逐根对象协议缺少scopes']
    raw=copy.deepcopy(response);roots=[]
    for s in raw['scopes']:
        if not isinstance(s,dict) or set(s)!=set(schema()['properties']['scopes']['items']['properties']):return plan,segments,['逐根对象scope字段不完整']
        objects=s.pop('root_objects');roots.append(objects)
    # Explicit new-protocol projection, not repair of an old malformed result.
    out,new,issues=previous.apply_one(plan,segments,raw)
    if issues:return plan,segments,issues
    for u,objects in zip(out['units'],roots):
        text=''.join(s['text'] for s in new[u['source_start_id']-1:u['source_end_id']]);classes=set()
        if not isinstance(objects,list) or not objects:return plan,segments,['每片缺少具体根对象目录']
        for obj in objects:
            if not isinstance(obj,dict) or set(obj)!={'subject','quote','category','role'}:return plan,segments,['具体根对象字段非法']
            if obj['category'] not in previous.CATEGORIES or obj['role'] not in {'facts','context'}:return plan,segments,['具体根对象类别或角色非法']
            if not isinstance(obj['subject'],str) or not obj['subject'].strip():return plan,segments,['具体根对象名称缺失']
            if not isinstance(obj['quote'],str) or not obj['quote'].strip() or obj['quote'] not in text:return plan,segments,['具体根对象引用不在本片逐字原文']
            if obj['role']=='facts':classes.add(obj['category'])
        if len(classes)>1:return plan,segments,['本片独立目录明确含不同实际根对象，应按原文转换另提完整连续边界：'+','.join(sorted(classes))]
        if classes and classes!={u['_physical_scope_v57']['category']}:return plan,segments,['根对象事实类别与片类别矛盾，不静默改分类']
        u['_physical_scope_v57']['root_objects']=copy.deepcopy(objects)
    return out,new,[]

def review(doc,plan,segments,runner):
    if doc.get('kind')!='文章' or doc.get('topic')!='北京臻澐项目口碑':return plan,segments,[],[]
    def work(task):
        i,u=task;selected=segments[u['source_start_id']-1:u['source_end_id']]
        local_segments=[dict(s,id=j+1) for j,s in enumerate(selected)]
        local_plan={'units':[dict(u,source_start_id=1,source_end_id=len(local_segments))]}
        payload={'source_text':doc['text'],'target_text':''.join(s['text'] for s in selected),'categories':previous.CATEGORIES}
        calls=[];audit=[]
        for attempt in range(2):
            response,m=runner.call(SYSTEM,payload,doc,'逐根对象与范围独立证据目录-v11.58' if not attempt else '根对象范围真实结构矛盾有界恢复-v11.58',response_schema=schema())
            calls.append(m)
            out,new,issues=apply_one(local_plan,local_segments,response) if m.get('status')=='success' else (local_plan,local_segments,['逐根对象目录API失败'])
            audit.append({'raw_root_object_response':copy.deepcopy(response),'issues':issues,'accepted':not issues})
            if not issues:return i,out,new,audit,calls
            payload=dict(payload,previous_response=response,repair_issues=issues)
        kept=copy.deepcopy(local_plan);kept['units'][0].setdefault('uncertainties',[]).append('逐根对象范围未核验，保留原文待审：'+'；'.join(issues))
        return i,kept,local_segments,audit,calls
    with ThreadPoolExecutor(max_workers=10) as pool:results=list(pool.map(work,enumerate(plan['units'])))
    out=copy.deepcopy(plan);out['units']=[];new=[];audit=[];calls=[]
    for i,part,spans,records,used in sorted(results):
        offset=len(new);new.extend(dict(s,id=offset+j+1) for j,s in enumerate(spans))
        out['units'].extend(dict(u,source_start_id=offset+u['source_start_id'],source_end_id=offset+u['source_end_id']) for u in part['units'])
        audit.append({'original_unit_index':i,'checks':records});calls+=used
    if ''.join(s['text'] for s in new)!=doc['text']:raise ValueError('逐根对象目录变换未无损覆盖全文')
    out['physical_scope_audit_v58']=audit
    return out,new,audit,calls
