"""Content-bound opaque adjacency keys, not model-counted boundary numbers.

Actual source intervals stay program-owned. Semantic decisions still come
from the model; no keyword determines article slicing boundaries here.
"""
import copy
import hashlib
import final_continuity_edges as legacy


SYSTEM=legacy.SYSTEM.replace('EDGE-0000','EDGE-输入实际键A').replace('EDGE-0001','EDGE-输入实际键B')
SYSTEM+='''\nedge_key是程序基于左右真实原文生成的不透明字符串，不能数段落或重新编号。
只审核本次edge_catalog列出的边界，全文用于消歧，不另外生成边界；输出键集合必须与输入完全一致。
不得根据记忆中的旧分区输出EDGE-0000等数字编号。每一决定先核对该键的left_text和right_text。
若左右包含一个主题的参数和解释，不因中间出现项目名就忽略承接；若一边本身混多个主题，应keep并说明需要重新分区，不吞并独立主题。'''


def catalog(excerpts):
    entries=[]
    for e in legacy.catalog(excerpts):
        key='EDGE-'+hashlib.sha256((str(e['left_unit_index'])+'\0'+e['left_text']+'\0'+e['right_text']).encode('utf-8')).hexdigest()[:16]
        entries.append(dict(e,edge_key=key))
    return entries


def model_catalog(excerpts):
    return [{k:e[k] for k in ('edge_key','left_text','right_text')} for e in catalog(excerpts)]


def decisions(response,entries,topic):
    """Preserve individually valid decisions, never infer missing boundaries."""
    expected={e['edge_key'] for e in entries};valid={};issues=[]
    checks=response.get('edges') if isinstance(response,dict) else None
    if not isinstance(checks,list):return {},sorted(expected),['边界决定列表缺失']
    grouped={k:[] for k in expected}
    for check in checks:
        key=check.get('edge_key') if isinstance(check,dict) else None
        if not isinstance(key,str) or key not in expected:
            issues.append('未知或重新编号的边界键');continue
        grouped[key].append(check)
    for key,items in grouped.items():
        if len(items)!=1:continue
        check=items[0];decision=check.get('decision');confidence=check.get('confidence')
        okay=decision in {'keep','same_object','comparison'}
        okay=okay and isinstance(check.get('why'),str) and bool(check['why'].strip())
        okay=okay and type(confidence) in (int,float) and .9<=confidence<=1
        if decision in {'same_object','comparison'}:
            okay=okay and check.get('theme') in legacy.THEMES
            okay=okay and isinstance(check.get('objects'),str) and bool(check['objects'].strip())
            okay=okay and (decision!='comparison' or topic=='北京臻澐项目口碑')
        if okay:valid[key]=copy.deepcopy(check)
    missing=sorted(expected-set(valid))
    return valid,missing,issues


def recovery_payload(original,response):
    entries=original['edge_catalog'];topic=original['topic']
    valid,missing,issues=decisions(response,entries,topic)
    if not missing:
        return original,valid,issues
    retry=copy.deepcopy(original)
    retry['edge_catalog']=[e for e in entries if e['edge_key'] in missing]
    retry['repair_issues']=issues+['只补本次目录中缺失/无效的实际边界键，已有效决定不重复返回']
    retry.pop('previous_output',None)
    return retry,valid,issues


def merge_recovery(original,retained,repaired):
    entries=original['edge_catalog'];missing=[e for e in entries if e['edge_key'] not in retained]
    recovered,unresolved,issues=decisions(repaired,missing,original['topic'])
    if issues or unresolved:
        return None,issues+['边界缺项有界恢复仍不完整，未采用部分合并']
    merged=dict(retained,**recovered)
    return {'edges':[merged[e['edge_key']] for e in entries]},[]


def apply(plan,response,topic,excerpts):
    entries=catalog(excerpts)
    if len(plan.get('units') or [])!=len(excerpts):return plan,['边界目录与实际分区数量不一致']
    checks=response.get('edges') if isinstance(response,dict) else None
    keys=[c.get('edge_key') for c in checks] if isinstance(checks,list) and all(isinstance(c,dict) for c in checks) else None
    expected={e['edge_key'] for e in entries}
    if (keys is None or not all(isinstance(k,str) for k in keys)
            or len(keys)!=len(expected) or set(keys)!=expected):
        return plan,['实际原文边界键缺失、重复或未知；不采用模型重新计数的边界']
    lookup={e['edge_key']:f"EDGE-{e['left_unit_index']:04d}" for e in entries}
    converted=copy.deepcopy(response)
    for check in converted['edges']:
        check['source_edge_key']=check['edge_key']
        check['edge_key']=lookup[check['edge_key']]
    merged,issues=legacy.apply(plan,converted,topic)
    if not issues:merged['final_continuity_source_key_audit']=copy.deepcopy(response)
    return merged,issues
