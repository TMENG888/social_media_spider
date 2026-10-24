"""Disjoint opaque source/prose references for independent factual review.

This protocol avoids treating a prose ordinal as a source ordinal. Validation
only proves reference coverage; the reviewer still must judge factual support.
"""
import hashlib
import prose_claim_evidence_review as legacy
from label_evidence_reference import evidence_catalog
from prose_speaker_catalog import source_catalog
from prose_living_impact_scope import issues as living_impact_issues
from prose_source_constraints import issues as source_constraint_issues


SYSTEM = legacy.SYSTEM.split('输出：', 1)[0].replace('fragment_id', 'prose_key')
SYSTEM += '''
两套目录的键完全独立：prose_key只标识待审文案片段，source_key只标识实际原文。
原文中的子评论序号不是证据键。source目录speaker由程序从原文标题读取，续句仍属于该speaker。
speaker仅是逐字昵称，不证明职业。每个prose_key须恰好审核一次，支持依据选择source_keys。
不能按文案序号猜原文位置：第四条文案可以由第五条原文支持，必须核对所选键的实际内容。
片段支持和主要事实覆盖分开判断；摘要不穷举次要数字，但不能把有条件/有限影响改成无条件严重影响。
程度限制和不同声音是核心事实：例如“能听到但不影响日常”，摘要只留下“听到噪音、很害怕”即遗漏生活影响限定，coverage必须判false。
允许省略次要配置或姓名，不允许删掉会改变主要评价程度的“不影响、偶尔、仅在室外”等限制。
指代与比较对象也必须有据：“比这小多了的都老远能听到”没有明示楼盘，摘要改为“周边小楼盘能远距离听到”即新增对象类别及位置，应判unsupported。不能仅凭同一讨论里有“小区”就给另一发言者的“这”填成楼盘。指代不能确认时可省略次要附和，不必穷举发言者。
逐对象检查评价：甲地块噪音大、乙北侧可能较好，回复“最北侧也没用”不能自动变成乙地块也受同样噪音影响。指代不能确认就保留泛指或不写这项比较，不向最近出现的项目名移植。
“没听过；如果二选一可能A好一点”只支持相对选择，不支持A尚可、可以接受或噪音不大。“环境吵；另一人说堵车”不支持堵车导致更吵。仅有“大飞机[视频]”不支持噪音视频，未读取媒体不能添加感官证据。
原文具体事件加回复附和时，摘要必须写事件，不能只写附和。例如“雨天用设备清理积水；回复称附近人才了解”要保留雨天清积水，不只说这是附近人的经验。
输出JSON：{"checks":[{"prose_key":"PROSE-输入实际键","status":"supported/unsupported/uncertain",
"source_keys":["SRC-输入实际键"],"why":"逐项对象、发言者、数值、状态的核对理由","confidence":0.95}],
"coverage":{"captures_primary_points":true,"source_keys":["SRC-输入实际键"],
"why":"核心事实、主要限定及不同声音的覆盖依据或具体遗漏","confidence":0.95}}。
不改写文案。每个决定独立核对，不因已有审核或高置信度放行。
'''


def prose_catalog(prose):
    return [dict(e, prose_key='PROSE-'+hashlib.sha256(
        (str(e['start'])+'\0'+e['text']).encode('utf-8')).hexdigest()[:12])
        for e in evidence_catalog(str(prose or ''))]


def payload(source, prose, identity_context=''):
    return {'source_text':source,'identity_context':identity_context,
        'source_evidence_catalog':[{k:e[k] for k in ('source_key','speaker','text')}
                                   for e in source_catalog(source)],
        'prose_catalog':[{k:e[k] for k in ('prose_key','text')}
                         for e in prose_catalog(prose)]}


def verify(source, prose, response):
    sources={e['source_key']:e['evidence_id'] for e in source_catalog(source)}
    fragments={e['prose_key']:e['evidence_id'] for e in prose_catalog(prose)}
    checks=response.get('checks') if isinstance(response,dict) else None
    if not fragments or not isinstance(checks,list) or not all(isinstance(c,dict) for c in checks):
        return False,[{'reason':'独立文案原文键审核协议不完整'}]
    keys=[c.get('prose_key') for c in checks]
    if not all(isinstance(k,str) for k in keys) or len(keys)!=len(fragments) or set(keys)!=set(fragments):
        return False,[{'reason':'文案键遗漏、重复或未知，未逐片完整审核'}]

    def resolve(keys):
        if (not isinstance(keys,list) or not keys or
                not all(isinstance(k,str) and k in sources for k in keys) or len(keys)!=len(set(keys))):
            return None
        return [sources[k] for k in keys]

    converted=[]
    for check in checks:
        converted.append(dict(check,fragment_id=fragments[check['prose_key']],
                              source_evidence_ids=resolve(check.get('source_keys'))))
    coverage=response.get('coverage')
    if isinstance(coverage,dict):
        coverage=dict(coverage,source_evidence_ids=resolve(coverage.get('source_keys')))
    okay,audit=legacy.verify(source,prose,{'checks':converted,'coverage':coverage})
    omissions=living_impact_issues(source,prose)+source_constraint_issues(source,prose)
    return okay and not omissions,audit+omissions
