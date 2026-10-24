"""Model-owned final adjacent grouping, including coherent T2 comparisons.

Not a keyword, length, tag-count or similarity boundary rule. Preserve complete
ordered source and regenerate all tags/prose after a verified grouping.
"""
import copy

THEMES={'floorplan','clubhouse','solution','facility','issue','property_fact','intro'}
SYSTEM='''只输出JSON。输入是全文及已经逐片划定的连续原文，最后核对是否把一个完整主题拆得过细。
你决定相邻groups，不按字数、标签数量或关键词切分。所有unit_index按顺序恰好覆盖一次，不能跨中间主题拼贴。
同一完整户型的参数、紧接的解释、设备及优缺点保持整体；同一会所设施列表整体；一个施工方案步骤整体。
专题二：同一栏目同一主题的甲乙项目连续对比应为comparison一组，而不是仅因项目名称拆两行。
例如甲乙层高参数、3.4米设备后净高解释、两者户型尺度优缺点连续构成一个floorplan比较，不让参数和解释重复层高标签。
甲乙教育连续对比可为facility一组，但甲项目教育和甲项目交通不能合并；园林与会所也不能仅因同项目合并。
专题一不合并不同项目/不同户型的独立介绍，只允许same_object。不同对象的真实差异不能去重掉。
开场连续研究背景可为intro，不能把整篇项目介绍称intro吞并多个独立主题。前后有关/无关混合不合并。
单片kind=keep；多片kind=same_object或comparison，每组说明具体对象、唯一主题、连续承接原因。
允许theme：floorplan、clubhouse、solution、facility、issue、property_fact、intro。不确定保持keep。
返回{"groups":[{"unit_indices":[0],"kind":"keep"},
{"unit_indices":[1,2],"kind":"comparison","theme":"floorplan","same_topic":true,
"objects":"甲乙两个项目户型","why":"同一连续户型主题的参数与解释对比","confidence":0.95}]}。
不生成引文、标签或摘要，不删除不同观点或任何原文。'''


def apply(plan,response,topic):
    units=plan.get('units');groups=response.get('groups') if isinstance(response,dict) else None
    if not isinstance(units,list) or not isinstance(groups,list) or not groups:return plan,['最终连续合并缺少groups']
    indices=[]
    for group in groups:
        if not isinstance(group,dict):return plan,['最终连续合并组结构错误']
        ids=group.get('unit_indices')
        if not isinstance(ids,list) or not ids or any(type(i) is not int for i in ids):return plan,['最终连续合并编号非法']
        indices+=ids
    if indices!=list(range(len(units))):return plan,['最终连续合并遗漏、重复、逆序或跨片']
    output=copy.deepcopy(plan);output['units']=[]
    for group in groups:
        ids=group['unit_indices'];originals=[units[i] for i in ids]
        if len(ids)==1:
            if group.get('kind')!='keep':return plan,['单片最终连续组必须keep']
            output['units'].append(copy.deepcopy(originals[0]));continue
        kind=group.get('kind');confidence=group.get('confidence')
        if kind not in {'same_object','comparison'} or group.get('same_topic') is not True or group.get('theme') not in THEMES:
            return plan,['最终合并未确认完整独立主题']
        if kind=='comparison' and topic!='北京臻澐项目口碑':return plan,['专题一不同对象不得借比较强行合并']
        if type(confidence) not in (int,float) or not .9<=confidence<=1:return plan,['最终连续合并置信度不足']
        if any(not isinstance(group.get(k),str) or not group[k].strip() for k in ('objects','why')):
            return plan,['最终合并没有具体对象或理由']
        if len({u.get('relevant') for u in originals})!=1:return plan,['最终连续合并混入有关/无关区间']
        for field in ('project_name','brand','entity','city'):
            values={u[field] for u in originals if isinstance(u.get(field),str) and u[field].strip()}
            if kind=='same_object' and len(values)>1:return plan,['同一对象最终合并元信息冲突：'+field]
        merged=copy.deepcopy(originals[0]);merged['source_end_id']=originals[-1]['source_end_id']
        merged['scope_reason']=group['why'];merged['labels']=[];merged['summary']=merged['practice']=None
        merged['object_quote']=None # A comparison cannot borrow the first project's facts.
        if kind=='comparison':
            for field in ('project_name','brand','entity','city'):
                values={u[field] for u in originals if isinstance(u.get(field),str) and u[field].strip()}
                merged[field]=next(iter(values)) if len(values)==1 else None
            merged['project_ids']=list(dict.fromkeys(pid for u in originals for pid in u.get('project_ids',[])))
            merged['project_evidence']=[copy.deepcopy(e) for u in originals for e in u.get('project_evidence',[])]
        merged['uncertainties']=list(dict.fromkeys(str(x) for u in originals for x in u.get('uncertainties',[])))
        merged['_final_continuity_group']=copy.deepcopy(group)
        merged.setdefault('confidence',{})['boundary']=confidence;merged['confidence']['summary']=None
        output['units'].append(merged)
    output['final_continuity_audit']=copy.deepcopy(response)
    return output,[]
