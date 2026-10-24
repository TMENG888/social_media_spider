"""Staged final grouping protocol with actionable full-key recovery.

Canonicalizing a one-member group only keeps that original interval. It never
changes its source, relevance, labels or metadata, and never approves a merge.
"""
import copy
import post_split_scope_groups as grouping


SYSTEM=grouping.SYSTEM+'''
单成员无论是什么主题都写kind=singleton；same_object/comparison只用于至少两个相邻原区间。
每个actual_source_key必须原序完整保留。irrelevant不可删掉：若无关则独立singleton。
不改变对象的短互动只有能说明与当前完整方案的承接时才可role=bridge，不能只因原relevant=false就定irrelevant。
对象引导用object_frame，例如“接下来解释洗手间防臭”，紧接同对象配置属于完整方案的上下文。
若你判为irrelevant但理由又说“同对象、不改变对象的情绪过渡”，两者矛盾，必须重新判断而非删原区间。
当前完整方案的纠正问答与配置可连为同主题，后面转换为厨房等另一对象必须独立。
有repair_issues时纠正结构，不删除missing_source_keys，不把它们移到原序之外。
'''


def apply(doc,plan,segments,response):
    normalized=copy.deepcopy(response)
    if isinstance(normalized,dict) and isinstance(normalized.get('groups'),list):
        for group in normalized['groups']:
            if (isinstance(group,dict) and isinstance(group.get('members'),list)
                    and len(group['members'])==1 and group.get('kind') in {'singleton','same_object','comparison'}):
                group['kind']='singleton'
    out,issues=grouping.apply(doc,plan,segments,normalized)
    if not issues and isinstance(out,dict):
        out['post_split_raw_group_protocol']=copy.deepcopy(response)
    return out,issues


def coverage_issues(response,expected):
    groups=response.get('groups',[]) if isinstance(response,dict) else []
    used=[m.get('source_unit_key') for g in groups if isinstance(g,dict)
          for m in g.get('members',[]) if isinstance(m,dict)]
    return {'actual_source_keys':expected,'previous_source_keys':used,
            'missing_source_keys':[k for k in expected if k not in used],
            'unknown_source_keys':[k for k in used if k not in expected],
            'duplicate_source_keys':list(dict.fromkeys(k for k in used if used.count(k)>1)),
            'ordered_coverage_matches':used==expected}


def review(doc,plan,segments,runner):
    if doc.get('kind')!='文章' or len(plan['units'])<2:return plan,[],[],[]
    catalog=grouping.catalog(doc,plan,segments);expected=[e['source_unit_key'] for e in catalog]
    payload={'source_text':doc['text'],'topic':doc['topic'],'unit_catalog':catalog,'actual_source_keys':expected}
    calls=[];audit=[];candidate=plan;issues=[]
    for attempt in range(2):
        response,m=runner.call(SYSTEM,payload,doc,
            '最后拆分后主题完整键分组-v11.44' if not attempt else '最后主题分组缺键定位恢复-v11.44')
        calls.append(m)
        candidate,issues=apply(doc,plan,segments,response) if m.get('status')=='success' else (plan,['最终分组API失败'])
        coverage=coverage_issues(response,expected)
        audit.append({'response':response,'issues':issues,'key_coverage':coverage})
        if not issues:break
        payload=dict(payload,previous_response=response,repair_issues=issues,**coverage,
                     repair_instruction='按actual_source_keys原序恰好一次保留所有源区间。单成员singleton；真正无关段仍独立保留；不改变对象的短互动须独立判断是否为bridge，不得删除或跳拼。')
    return candidate,audit,calls,issues
