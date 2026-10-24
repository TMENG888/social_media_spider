"""Source-grounded physical-object transitions before final semantic grouping.

Model supplies every cut. Program only locates literal anchors and checks
lossless coverage. Independent scope categories prevent a later broad comparison
decision from concealing previously identified physical object transitions.
"""
import copy
from concurrent.futures import ThreadPoolExecutor
import local_granularity_repair as local

CATEGORIES=['floorplan','finishing','landscape','clubhouse','solution','education','medical','commercial',
    'transport','ecology','industry','planning','brand','price','positioning','adverse','decision','context','other']
SYSTEM='''只输出JSON。source_text为文章全文，target_text是本次唯一要审的连续区间，全文仅消歧。
按实际具体物理对象/方案和独立比较维度，记录此区间完整连续scopes。不是按标签或关键词切片。
每片先给具体subject和其内部逐字subject_evidence，再给scope_category，最后给原文起点。
根对象和子设施要区分：同一会所内泳池、茶室、健身可同片；同一户型内卧室、阳台、动线可同片；同一工法机制的部件/参数/后续纠正可同片。
室外园林景观与室内会所是不同具体根对象，不因同一公区/项目/栏目合一片。
教育、医疗、商业、交通、自然景观等是不同外部设施主题，不把所有周边配套合一片。
综述或选购建议若没有独立配置细节，可作为decision或context；不可把大量具体配置称context逃避物理对象核对。
跨两个项目的同一具体属性可以同片；如原序为甲庭园、甲会所、乙庭园、乙会所，必须原位记录四个连续根对象范围，不能跳拼两庭园或全叫会所。
合成例：甲项目外部庭园采用环形步道，室内会所设阅读与瑜伽区；乙外部庭园设置坡地，室内会所设健身与茶室。原位区分庭园与会所，设施列表保持整体。
合成反例：把前例全部称社区公区，或每个健身/茶室单独切片，均不合理。
每个起点由你按对象实际转换决定，不按字数/标签数。只有一个完整对象则scopes仅一项。
首项from_target_start=true，start_quote=null；后续false且start_quote为目标内实际片头15至40字，start_occurrence为真实出现次数。
各项须覆盖开头到结尾全部内容，含不相关过渡，不能删原文或借入目标外句子。
scope_reason及why仅写简短最终原文依据，不写内部反思。subject_evidence必须是本scope实际范围内的逐字连续短引文。
信心低或对象不明如实说明，不为了减少/增加片数强行确定。所有scopes是独立语义判断，先前判断不是事实权威。
返回{"scopes":[{"from_target_start":true,"start_quote":null,"start_occurrence":1,
"subject":"具体对象或主题","subject_evidence":"当前片内短原文","scope_category":"所给合法类别",
"scope_reason":"为何属于完整对象且没有夹入其他根对象","relevant":true,"boundary_confidence":0.95}],"why":"最终依据"}。'''

def schema():
    fields={'from_target_start':{'type':'boolean'},'start_quote':{'type':['string','null']},
        'start_occurrence':{'type':'integer','minimum':1},'subject':{'type':'string','minLength':1},
        'subject_evidence':{'type':'string','minLength':1},'scope_category':{'type':'string','enum':CATEGORIES},
        'scope_reason':{'type':'string','minLength':1},'relevant':{'type':'boolean'},
        'boundary_confidence':{'type':'number','minimum':0,'maximum':1}}
    return {'type':'object','properties':{'scopes':{'type':'array','minItems':1,'items':{'type':'object',
        'properties':fields,'required':list(fields),'additionalProperties':False}},'why':{'type':'string','minLength':1,'maxLength':240}},
        'required':['scopes','why'],'additionalProperties':False}

def apply_one(plan,segments,response):
    if not isinstance(response,dict) or set(response)!={'scopes','why'} or not isinstance(response.get('scopes'),list) or not response['scopes']:
        return plan,segments,['根对象语义目录协议无效']
    scopes=response['scopes']
    if not isinstance(response['why'],str) or not 1<=len(response['why'].strip())<=240:return plan,segments,['根对象最终理由缺失或过长']
    for i,s in enumerate(scopes):
        if not isinstance(s,dict) or set(s)!=set(schema()['properties']['scopes']['items']['properties']):return plan,segments,['根对象目录项字段非法']
        if s['scope_category'] not in CATEGORIES:return plan,segments,['根对象类别非法']
        if type(s['relevant']) is not bool or type(s['from_target_start']) is not bool:return plan,segments,['根对象布尔值非法']
        if s['from_target_start']!=(i==0) or (i==0 and s['start_quote'] is not None):return plan,segments,['根对象起点协议非法']
        if any(not isinstance(s[f],str) or not s[f].strip() for f in ('subject','subject_evidence','scope_reason')):return plan,segments,['根对象及原文依据缺失']
        if type(s['boundary_confidence']) not in (int,float) or not .9<=s['boundary_confidence']<=1:return plan,segments,['根对象边界置信度不足']
    repair={'unit_index':0,'action':'split' if len(scopes)>1 else 'keep','why':response['why'],'units':scopes if len(scopes)>1 else []}
    out,new_segments,issues=local.apply(plan,{'repairs':[repair]},segments,[0])
    if issues:return plan,segments,issues
    for s,u in zip(scopes,out['units']):
        text=''.join(e['text'] for e in new_segments[u['source_start_id']-1:u['source_end_id']])
        if s['subject_evidence'] not in text:return plan,segments,['根对象证据不在对应新片内，不能借同篇其他片']
        u['_physical_scope_v57']={'category':s['scope_category'],'subject':s['subject'],
            'evidence':s['subject_evidence'],'confidence':s['boundary_confidence']}
    return out,new_segments,[]

def review(doc,plan,segments,runner):
    if doc.get('kind')!='文章' or doc.get('topic')!='北京臻澐项目口碑':return plan,segments,[],[]
    def work(task):
        i,u=task;selected=segments[u['source_start_id']-1:u['source_end_id']]
        local_segments=[dict(s,id=j+1) for j,s in enumerate(selected)]
        local_plan={'units':[dict(u,source_start_id=1,source_end_id=len(local_segments))]}
        text=''.join(s['text'] for s in selected);payload={'source_text':doc['text'],'target_text':text,'categories':CATEGORIES}
        calls=[];audit=[]
        for attempt in range(2):
            response,m=runner.call(SYSTEM,payload,doc,'具体根对象连续目录-v11.57' if not attempt else '根对象目录实际协议恢复-v11.57',response_schema=schema())
            calls.append(m)
            out,new,issues=apply_one(local_plan,local_segments,response) if m.get('status')=='success' else (local_plan,local_segments,['根对象目录API失败'])
            audit.append({'response':copy.deepcopy(response),'issues':issues})
            if not issues:return i,out,new,audit,calls
            payload=dict(payload,previous_response=response,repair_issues=issues)
        kept=copy.deepcopy(local_plan)
        kept['units'][0].setdefault('uncertainties',[]).append('具体根对象目录未核验，原区间保留待审：'+'；'.join(issues))
        return i,kept,local_segments,audit,calls
    with ThreadPoolExecutor(max_workers=10) as pool:results=list(pool.map(work,enumerate(plan['units'])))
    out=copy.deepcopy(plan);out['units']=[];new=[];audit=[];calls=[]
    for i,part,spans,records,used in sorted(results):
        offset=len(new);new.extend(dict(s,id=offset+j+1) for j,s in enumerate(spans))
        out['units'].extend(dict(u,source_start_id=offset+u['source_start_id'],source_end_id=offset+u['source_end_id']) for u in part['units'])
        audit.append({'original_unit_index':i,'checks':records});calls+=used
    if ''.join(s['text'] for s in new)!=doc['text']:raise ValueError('具体根对象目录变换未无损覆盖全文')
    out['physical_scope_audit_v57']=audit
    return out,new,audit,calls

def merge_issues(plan,a,b,response):
    """Immutable independent classifications constrain later broad merges only."""
    if response.get('kind') not in {'comparison','same_object'}:return []
    facts={u.get('_physical_scope_v57',{}).get('category') for u in plan['units'][a:b+1]}
    facts-={None,'context'}
    if len(facts)>1:return ['独立原文根对象目录已证实不同具体范围，不能以综合比较/同项目吞并：'+','.join(sorted(facts))]
    return []
