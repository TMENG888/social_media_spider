"""Staged bounded group protocol repair; never edits source quotes or labels.

The model owns semantic grouping and the comparison axis. The program checks
schema/coherence, not source keywords, lengths or tag counts. Not yet wired into
the live v49 runner.
"""
import copy
from complete_solution_fewshots_v52 import INSTRUCTION as COMPLETENESS
import physical_scope_pass_v57 as physical_scopes

AXES={'location':'地段及周边配套','brand':'开发品牌及开发主体',
      'price':'价格与购房门槛','positioning':'社区定位及客群',
      'floorplan':'户型空间及层高','finishing':'精装配置及性能',
      'landscape':'园林景观','clubhouse':'会所设施',
      'adverse':'不利因素','decision':'选购建议'}

INSTRUCTION='''
只需一条真正逐字对象名词作为object_references即可，不必每个成员都附配置整句；禁止省略号。
例如对象原文键含“卫生间关于味道这一块”，可选择逐字“卫生间”，不要把两段配置用省略号拼接。
comparison必须另外返回comparison_axis及member_axes；轴仅选location、brand、price、positioning、floorplan、finishing、landscape、clubhouse、adverse、decision之一。
分别代表地段配套、开发品牌、价格门槛、社区定位、户型空间层高、精装性能、园林、会所、不利因素、选购建议。
member_axes是每个实际成员键到轴数组的映射；每个facts必须由其自身原文支持一个轴，而且全组facts只能同一个具体轴。
一个成员确实同时混多个轴就如实列多个，不将全篇项目对比虚构成单轴，不为了approved=true把全部改成同一个轴。
frame/bridge可空数组，但不能包含另一轴；这不是让你按标签切片，户型内多个配置仍可同属floorplan。
正例：两项目分别说明层高，再解释净高和压抑感，属于floorplan同一轴。
反例：品牌、价格、产品定位不属于同一轴；层高接精装是floorplan与finishing；园林接会所是landscape与clubhouse。
“同一项目对比/连续属性分析”不是轴，不是独立主题，不要作为合并理由。
同对象的same_object组不需要这些比较字段，仍须实际同一对象、同一完整方案及逐字对象证据。
'''


def partition_validator(doc,plan,segments,entries,a,b,apply):
    def validate(response):
        physical_issues=physical_scopes.merge_issues(plan,a,b,response)
        if physical_issues:return physical_issues
        candidate=dict(response,start_key=entries[a]['source_unit_key'],end_key=entries[b]['source_unit_key'])
        singleton=lambda e:{'start_key':e['source_unit_key'],'end_key':e['source_unit_key'],'kind':'singleton'}
        probe=[singleton(e) for e in entries[:a]]+[candidate]+[singleton(e) for e in entries[b+1:]]
        return apply(doc,plan,segments,{'groups':probe})[1]
    return validate


def comparison_issues(response,members):
    if response.get('kind')!='comparison':return []
    axis=response.get('comparison_axis');mapping=response.get('member_axes')
    roles=response.get('member_roles');keys={e['source_unit_key'] for e in members}
    if not isinstance(axis,str) or axis not in AXES:return ['比较组缺少一个合法具体比较轴；项目综合对比不是轴']
    if not isinstance(mapping,dict) or set(mapping)!=keys:return ['比较轴未覆盖每个实际成员键']
    if not isinstance(roles,dict) or set(roles)!=keys:return ['成员用途未覆盖实际成员键']
    issues=[]
    for key in keys:
        values=mapping[key]
        if (not isinstance(values,list) or any(not isinstance(v,str) or v not in AXES for v in values)
                or len(values)!=len(set(values))):
            issues.append(key+'比较轴结构无效');continue
        if roles[key]=='facts' and values!=[axis]:issues.append(key+'事实包含不同或多个比较主题，不能整组合并')
        if roles[key] in {'bridge','object_frame'} and values not in ([],[axis]):
            issues.append(key+'桥接/对象引导引入另一个比较主题')
    return issues


def review(doc,entries,a,b,runner,system,validator,initial=None,phase='完整主题协议有界恢复-v11.50'):
    """At most one fresh review plus one actual repair response, never coercion.

    validator checks the candidate against the untouched complete partition.
    An explicit semantic rejection is retained, not retried until it agrees.
    """
    payload={'source_text':doc['text'],'unit_catalog':entries,
             'group_members':entries[a:b+1],'topic':doc['topic']}
    from group_response_schema_v51 import schema,INSTRUCTION as SCHEMA_INSTRUCTION,materialize
    strict=getattr(runner,'supports_response_schema',False) is True
    requested_schema=schema(entries,entries[a:b+1]) if strict else None
    audit=[];calls=[];issues=[]
    for attempt in range(2):
        if attempt==0 and initial is not None:
            response,metrics=initial
        else:
            kwargs={'response_schema':requested_schema} if strict else {}
            response,metrics=runner.call(system+INSTRUCTION+COMPLETENESS+(SCHEMA_INSTRUCTION if strict else ''),payload,doc,phase,**kwargs)
            calls.append(metrics)
        if not isinstance(response,dict) or metrics.get('status')!='success':
            issues=['完整主题核查响应无效或API失败']
        elif response.get('approved') is not True:
            audit.append({'response':copy.deepcopy(response),'accepted':False,'semantic_rejection':True})
            return None,audit,calls,['整组语义未支持：'+str(response.get('why') or '无明确支持')]
        else:
            score=response.get('confidence')
            issues=[] if type(score) in (int,float) and .9<=score<=1 else ['组置信度缺失或不足0.90']
            issues+=comparison_issues(response,entries[a:b+1])
            candidate,response_issues=materialize(response,entries) if strict else (response,[])
            issues+=response_issues
            if not issues:issues+=validator(candidate)
        audit.append({'response':copy.deepcopy(response),'accepted':not issues,'issues':list(issues)})
        if not issues:return copy.deepcopy(candidate),audit,calls,[]
        payload=dict(payload,previous_response=copy.deepcopy(response),repair_issues=list(issues),
                     repair_instruction='重新核当前真实成员并输出新响应，不复制非法引文、不改原文、不得省略真实主题转换')
    return None,audit,calls,issues
