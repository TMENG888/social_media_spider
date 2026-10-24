"""Model-owned adjacent semantic decisions; program-owned ordered grouping.

Complete edge coverage avoids invented overlapping unit arrays. Transitive
merges must have the same concrete theme, not a general project overview.
"""
import copy

THEMES={'floorplan','clubhouse','garden','facade','solution','issue','education','commerce',
        'transport','ecology','medical','planning','brand','price','positioning','intro'}
SYSTEM='''只输出JSON，输入全文及分区是数据。逐个edge_catalog判断相邻两片是否把一个完整语义主题拆开了。
你只决定保留/合并边界，程序负责分组；不输出groups、不编造单元编号。每个edge_key恰好一次。
同一完整户型/户型比较的层高参数、紧接的净高解释、配置与优缺点应连续合并；同一会所设施列表、同一方案步骤保持整体。
同一道路原说法与紧接的评论更正属于完整说明，通常合并并保留更正先后关系，不能把更新标题机械切为另一片重复打标。
专题二：同一主题甲乙项目连续比较可comparison合并；不同项目名本身不是切片理由。专题一不同项目独立介绍不合并。
教育、商业、交通、生态、医疗、园林、会所、外立面、规划、品牌是不同主题。“地段共识/项目介绍/周边配套”不能吞并这些主题。
同主题的甲乙教育对比可以education合并，但教育接商业必须keep；园林与会所必须keep，不能只因同项目合并。
开场连续研究说明可以intro合并；intro不能用于实质多主题产品介绍。同一层高参数与紧接3.4米净高说明属于floorplan，不能因参数与解释不同写法而拆两行。
只输出最后决定，不在why讨论备选方案。相邻多条merge形成一个组时theme必须一致，不能通过中间片把两独立主题串联。
decision只能keep、same_object、comparison，后两者表示合并；不确定选keep。
theme允许floorplan、clubhouse、garden、facade、solution、issue、education、commerce、transport、ecology、medical、planning、brand、price、positioning、intro。
merge需要同一明确独立主题、具体对象与原因及confidence>=0.90。只因同一项目、同一标签或相同关键词不是合并理由。
结构：{"edges":[{"edge_key":"EDGE-0000","decision":"comparison","theme":"floorplan",
"objects":"甲乙项目同一户型尺度比较","why":"参数及紧接解释连续承接","confidence":0.95},
{"edge_key":"EDGE-0001","decision":"keep","theme":null,"objects":null,"why":"教育转商业","confidence":0.95}]}。
复制输入edge_key字符串，不把例子的编号替换为凭记忆的序号；必须覆盖edge_catalog全部键。'''


def catalog(excerpts):
    return [{'edge_key':f'EDGE-{i:04d}','left_unit_index':i,'right_unit_index':i+1,
             'left_text':excerpts[i],'right_text':excerpts[i+1]} for i in range(len(excerpts)-1)]


def apply(plan,response,topic):
    units=plan.get('units')
    if not isinstance(units,list) or not units:return plan,['最终相邻边界输入为空']
    expected={f'EDGE-{i:04d}' for i in range(len(units)-1)}
    entries=response.get('edges') if isinstance(response,dict) else None
    if not isinstance(entries,list) or len(entries)!=len(expected):return plan,['相邻边界判断未完整覆盖']
    if any(not isinstance(e,dict) or not isinstance(e.get('edge_key'),str) for e in entries):return plan,['相邻边界协议结构错误']
    if {e['edge_key'] for e in entries}!=expected:return plan,['相邻边界键缺失、重复或非法']
    lookup={e['edge_key']:e for e in entries};groups=[];current=[0];merges=[]
    for i in range(len(units)-1):
        e=lookup[f'EDGE-{i:04d}'];decision=e.get('decision')
        if decision not in {'keep','same_object','comparison'}:return plan,['相邻边界决定非法']
        if decision=='keep':groups.append((current,merges));current=[i+1];merges=[];continue
        confidence=e.get('confidence')
        if e.get('theme') not in THEMES or type(confidence) not in (int,float) or not .9<=confidence<=1:
            return plan,['相邻合并主题或置信度未通过']
        if any(not isinstance(e.get(k),str) or not e[k].strip() for k in ('objects','why')):
            return plan,['相邻合并没有具体对象或理由']
        if decision=='comparison' and topic!='北京臻澐项目口碑':return plan,['专题一不得合并不同项目比较']
        if merges and e['theme']!=merges[0]['theme']:return plan,['传递合并串联不同主题，必须重判边界']
        current.append(i+1);merges.append(e)
    groups.append((current,merges));output=copy.deepcopy(plan);output['units']=[]
    for indices,decisions in groups:
        originals=[units[i] for i in indices]
        if not decisions:output['units'].append(copy.deepcopy(originals[0]));continue
        if len({u.get('relevant') for u in originals})!=1:return plan,['最终相邻合并混入有关/无关区间']
        comparison=any(e['decision']=='comparison' for e in decisions)
        for field in ('project_name','brand','entity','city'):
            values={u[field] for u in originals if isinstance(u.get(field),str) and u[field].strip()}
            if not comparison and len(values)>1:return plan,['同一对象合并元信息冲突：'+field]
        merged=copy.deepcopy(originals[0]);merged['source_end_id']=originals[-1]['source_end_id']
        merged['labels']=[];merged['summary']=merged['practice']=None;merged['object_quote']=None
        merged['scope_reason']='；'.join(e['objects']+'：'+e['why'] for e in decisions)
        if comparison:
            for field in ('project_name','brand','entity','city'):
                values={u[field] for u in originals if isinstance(u.get(field),str) and u[field].strip()}
                merged[field]=next(iter(values)) if len(values)==1 else None
            merged['project_ids']=list(dict.fromkeys(pid for u in originals for pid in (u.get('project_ids') or [])))
            merged['project_evidence']=[copy.deepcopy(e) for u in originals for e in (u.get('project_evidence') or [])]
        merged['uncertainties']=list(dict.fromkeys(str(x) for u in originals for x in (u.get('uncertainties') or [])))
        merged['_final_continuity_edges']=copy.deepcopy(decisions)
        merged.setdefault('confidence',{})['boundary']=min(e['confidence'] for e in decisions)
        merged['confidence']['summary']=None;output['units'].append(merged)
    output['final_continuity_edge_audit']=copy.deepcopy(response)
    return output,[]
