"""Staged label-relative duplicate protocol; never hard-code a tag grant/drop.

Only a future explicitly wired reviewer uses this. Existing live v58 is frozen.
Structural consistency alone is not semantic precision or recall evidence.
"""
from prose_speaker_catalog import source_catalog
from structured_response_validation_v58 import issues as schema_issues
from comment_identity_protocol_v59 import obj,TEXT,KEYS,resolve

SYSTEM='''只核查A/B的一个指定标签。完整文章帮助区分项目/户型/对象，不提供片外标签事实。
先读标签完整路径及定义，写target_property，再把A/B证据分别投影到该属性，列出全部有据事实。
不能比较整个句子措辞代替比较标签事实。
独立合成正例：同一户型A写“四居洋房”、B写“低密洋房”，若当前标签是物业形态/洋房，
两侧投影均为洋房，四居和低密不是洋房标签下的两个事实。不能用其他标签属性宣布洋房标签不重复。
反例：A为甲项目洋房、B为乙项目洋房，值相同但对象不同，不归并。
反例：当前是建筑面积，A为110平方米户型、B为140平方米户型，不归并。
反例：同一标签A有95及108两个面积，B仅重复95，属于partial_overlap，不能移除A的整个标签。
状态、不同评价者的主张、不同时间的改变要保留；开发商否认与住户投诉不是同一评价事实。
每侧事实选各自原文键，说明对象、标签内属性值及会改变该事实的限定。装饰性修饰、其他标签的属性放ignored_other_properties。
verdict取same_fact/different_fact/partial_overlap/uncertain。different_fact必须有不同对象，或明确different_in_target_property=true；
仅其他属性不同不能宣布different_fact。same_fact要求同对象、目标属性事实相同，选A/B保留；有独立事实不可whole_label_removable=true。
不确定是有效结果，不为减少重复反复提高置信度。不输出过程思考，只给有证据的最终理由。'''

FACT=obj({'object':TEXT,'value':TEXT,'evidence_keys':KEYS,'qualifiers':{'type':'array','items':TEXT}})
SCHEMA=obj({'target_property':TEXT,'facts_a':{'type':'array','items':FACT,'minItems':1},
    'facts_b':{'type':'array','items':FACT,'minItems':1},
    'same_object':{'type':['boolean','null']},'different_in_target_property':{'type':['boolean','null']},
    'ignored_other_properties':{'type':'array','items':TEXT},
    'verdict':{'type':'string','enum':['same_fact','different_fact','partial_overlap','uncertain']},
    'whole_label_removable':{'type':'boolean'},'keep_side':{'type':['string','null'],'enum':['A','B',None]},
    'why':TEXT,'confidence':{'type':'number','minimum':0,'maximum':1}})

def catalogs(left,right):
    return ([dict(e,source_key='A-'+e['source_key']) for e in source_catalog(left)],
            [dict(e,source_key='B-'+e['source_key']) for e in source_catalog(right)])

def payload(left,right,definition,identity_context):
    a,b=catalogs(left,right)
    return {'label_definition':definition,'source_identity_context':identity_context,
            'A':{'excerpt':left,'catalog':a},'B':{'excerpt':right,'catalog':b}}

def verify(left,right,response):
    issues=schema_issues(response,SCHEMA)
    if issues:return None,issues
    a,b=catalogs(left,right);mapped=[]
    for side,entries in [('a',a),('b',b)]:
        facts=[]
        for fact in response['facts_'+side]:
            quote=resolve(fact['evidence_keys'],entries)
            if not quote:issues.append(side+'事实引用缺失/重复/越界/错侧');continue
            facts.append(dict(fact,verified_quote=quote))
        mapped.append(facts)
    verdict=response['verdict']
    if verdict=='different_fact' and not (response['same_object'] is False or response['different_in_target_property'] is True):
        issues.append('不同事实决定没有不同对象或标签目标属性差异')
    if verdict=='same_fact' and not (response['same_object'] is True and response['different_in_target_property'] is False):
        issues.append('同事实决定与对象/目标属性判断矛盾')
    if response['whole_label_removable'] and not (verdict=='same_fact' and response['keep_side'] in ('A','B')):
        issues.append('部分重叠/不同/未知事实不能删除整个标签')
    if verdict!='same_fact' and response['keep_side'] is not None:
        issues.append('非同事实不能选择保留侧')
    if issues:return None,issues
    return dict(response,verified_facts_a=mapped[0],verified_facts_b=mapped[1],
                safe_to_remove=verdict=='same_fact' and response['whole_label_removable']
                    and response['confidence']>=.9),[]

def review(left,right,definition,identity_context,doc,runner):
    from bounded_structural_review_v59 import review as structural_review
    raw,calls,audit,errors=structural_review(SYSTEM,payload(left,right,definition,identity_context),
        SCHEMA,doc,'重复标签目标属性投影核验-v11.59',runner)
    if errors:return None,calls,audit,errors
    decision,issues=verify(left,right,raw)
    return decision,calls,audit,issues
