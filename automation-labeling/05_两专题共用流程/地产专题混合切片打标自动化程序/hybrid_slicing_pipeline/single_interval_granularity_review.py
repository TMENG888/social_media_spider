"""Review one real interval at a time with full source; model owns boundaries.

Avoid cross-unit index drift. A proposed split is accepted only after literal
anchors and complete source retention pass the existing transformation contract.
Comments bypass this stage. Failed decisions retain source with review reasons.
"""
import copy
from concurrent.futures import ThreadPoolExecutor
import local_granularity_repair as local

SYSTEM=local.SYSTEM+'''
本次目录只有一个repair_target，unit_index固定0，不按全文段落编号猜索引。
只核目标excerpt实际文本。目标中若先讲会所，后转周边商业、江距或交通，要在实际转折处分开。
同一工法方案的多个部件保持整体；若结尾又问另一场景的工法或仅节目邀约，应保留各段但区分主题。
客群定位/社区氛围与房屋层高是独立主题，不把前一栏目尾巴并入下一栏目层高参数。
不能因都是同项目、同一文章栏目、同一个质量标签，就吞并独立对象或方案。
主张split时必须给出实际多个原文起点；keep必须说明为何所有内容属于同一完整对象/主题。
每个新片给boundary_confidence，不能借原片置信度冒充新边界验收。
只输出最终JSON，不输出分析过程。'''
SYSTEM+='''\n全文source_text仅作背景，唯一可改边界的文本是target_text，不能在目标外另选主题。目标之外已经有边界；不需要再复制其相邻段。
split首片使用{"from_target_start":true,"scope_reason":"开头实际对象与主题","relevant":true,"boundary_confidence":0.95}，程序引用目标原有起点，完整保留开头。首片不能从中段开始，不能漏前述管道事实而从后面的空鼓开始。
之后每片仍以目标内实际start_quote、start_occurrence、scope_reason、relevant、boundary_confidence给出。from_target_start只允许首片为true，不是让程序决定新的边界。
每个问答框架不等于一个语义对象：先问卫生间防反味，后问厨房烟道密封，是两个完整对象/方案，分别保留；同一卫生间的存水弯、补水及其参数仍保持一片。质量投诉中管道、墙面缺陷、电梯承诺、消防设施是不同对象，不因为同一个质量标签合成一个大段。'''
SYSTEM+='''\n同一栏目标题不决定具体对象。“园林与会所”可以同时讨论室外景观布局和会所室内功能空间，这两者不是同一具体比较轴。
园林风格、景观动线与种植配置可作为完整园林介绍；会所面积、泳池、茶室等可作为完整会所介绍，不把两者全吞成社区公区一片。
若甲项目园林后接甲会所，再讲乙园林和乙会所，应保留实际连续顺序，不跨中间会所把两个园林拼贴成一片。
同一户型内部的空间布局和尺度解释仍可整体，同一会所的多种设施仍可整体，不能按设施名、标签数或示例关键词机械拆片。
实际分界只由你根据目标原文具体对象转换选择逐字起点；证据不明时说明不确定，不猜原文对象。'''


def review(doc,plan,segments,runner,_depth=0,_indices=None):
    if doc.get('kind')!='文章':return plan,segments,[],[]
    targets=[]
    for i,u in enumerate(plan['units']):
        if _indices is not None and i not in _indices:continue
        text=''.join(s['text'] for s in segments[u['source_start_id']-1:u['source_end_id']])
        targets.append((i,text,u))
    def check(task):
        i,text,u=task
        payload={'source_text':doc['text'],'target_text':text,'topic':doc['topic'],'repair_targets':[
            {'unit_index':0,'excerpt':text,'scope_reason':u.get('scope_reason'),'relevant':u.get('relevant')}]}
        calls=[];attempts=[];accepted=None
        selected=segments[u['source_start_id']-1:u['source_end_id']]
        # Validate independently against this exact interval before combining.
        test_segments=[dict(s,id=j+1) for j,s in enumerate(selected)]
        test_plan={'units':[dict(u,source_start_id=1,source_end_id=len(test_segments))]}
        for attempt in range(2):
            raw,m=runner.call(SYSTEM,payload,doc,
                '单区间实际原文粒度核查-v11.29' if not attempt else '单区间粒度协议恢复-v11.29')
            calls.append(m)
            _,_,issues=local.apply(test_plan,raw,test_segments,[0])
            attempts.append({'response':raw,'issues':issues,'status':m['status']})
            if m['status']=='success' and not issues:
                accepted=copy.deepcopy(raw['repairs'][0]);accepted['unit_index']=i;break
            payload=dict(payload,repair_issues=issues)
        return i,accepted,calls,attempts
    with ThreadPoolExecutor(max_workers=10) as pool:decisions=list(pool.map(check,targets))
    pending=copy.deepcopy(plan);repairs=[];audit=[];calls=[]
    for i,accepted,metrics,attempts in decisions:
        calls+=metrics;audit.append({'original_unit_index':i,'review_depth':_depth,'accepted':accepted,'attempts':attempts})
        if accepted:repairs.append(accepted)
        else:pending['units'][i].setdefault('uncertainties',[]).append(
            '单区间独立粒度核验未完成：保留原文边界待人工审核，不视为keep验收')
    out,new_segments,issues=local.apply(pending,{'repairs':repairs},segments,
                                         [r['unit_index'] for r in repairs])
    if issues:
        out=pending;new_segments=segments
        for u in out['units']:u.setdefault('uncertainties',[]).append('单区间合并变换失败：'+'；'.join(issues))
    elif _depth==0:
        # Check newly created children once. A split of an over-broad parent
        # can still leave an over-broad child; do not silently certify it.
        ranges=[(segments[plan['units'][r['unit_index']]['source_start_id']-1]['start'],
                 segments[plan['units'][r['unit_index']]['source_end_id']-1]['end'])
                for r in repairs if r['action']=='split']
        children=[i for i,u in enumerate(out['units']) if any(
            start<=new_segments[u['source_start_id']-1]['start']
            and new_segments[u['source_end_id']-1]['end']<=end for start,end in ranges)]
        if children:
            out,new_segments,child_audit,child_calls=review(doc,out,new_segments,runner,1,children)
            audit+=child_audit;calls+=child_calls
    out['single_interval_granularity_audit']=audit
    return out,new_segments,audit,calls
