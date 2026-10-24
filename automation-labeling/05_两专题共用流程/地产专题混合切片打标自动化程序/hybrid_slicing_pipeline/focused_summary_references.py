"""Opaque source keys prevent confusion with child-comment ordinals.

Speaker attribution follows literal comment headers, not inferred persona.
Reference grounding is not a substitute for independent semantic auditing.
"""
import hashlib
import re
from label_evidence_reference import evidence_catalog

SYSTEM='''只输出JSON。为当前完整评论的80字摘要选1至5个核心说法，先区分发言者和具体评价对象。
只使用source_evidence_catalog中的source_key字符串，不能用子评论编号或整数序号代替。
每个source_key对应实际原文片段，speaker由程序从原文发言者标题回填，不是职业身份。
某句未重复昵称仍属于对应speaker；不能将MM的话归给weixiao、将朱房双子的位置归给保利熙瑞。
同一主题选贯穿讨论的主要事实、不同态度和实质问题，不穷举次要房源、数字或附和。
保留改变评价程度的限定和不同声音：如能听到但不影响日常，应选成完整有限影响的claim，不能只选前半句的响声或害怕。
原文仅说朱房双子临快速路，不概括成海淀楼盘都临快速路；一人纠结不代表所有购房者。
每个claim只表达一对象的一说法，保留评价、预测、建议、提问或转述性质。
claim不是自由补全：大小比较里的“这/比这小的”没有明示类别，不能补成楼盘、房源或周边位置；可不选这种次要附和。
主要说法须选完整场景差异：家中听不到但户外低频可闻是一条完整claim；开窗可闻但不影响生活、户外声音大也须整体保留。优先省略昵称、附和与次要比较，不省略限定。
正文仅有大飞机及[视频]不能选出噪音；并列抱怨堵车和噪音不能选出堵车让噪音更大的因果。
actor_quote选所引用片段的speaker原样名称或null；object_quote必须在所选证据中逐字存在，未知可null。
返回{"claims":[{"actor_quote":"逐字发言者或null","object_quote":"逐字对象词或null",
"claim":"忠实具体核心说法","evidence_keys":["SRC-实际键"],"confidence":0.95}]}。
不能生成摘要、标签、职业身份或审计说明。返回前核对每个键对应的文本确实包含该对象和事实。
如果有repair_issues，纠正错配的键及事实，不能仅把键换成猜测值。'''


def catalog(source):
    headers=[(m.start(),m.group(1)) for m in re.finditer(r'【(?:父评论|子评论\d*)｜([^】]+)】',source)]
    result=[]
    for span in evidence_catalog(source):
        preceding=[h for h in headers if h[0]<=span['start']]
        speaker=preceding[-1][1] if preceding else None
        # A fragment with a mid-fragment speaker switch is not given one actor.
        if any(span['start']<h[0]<span['end'] for h in headers):speaker=None
        key='SRC-'+hashlib.sha256((str(span['start'])+'\0'+span['text']).encode('utf-8')).hexdigest()[:12]
        result.append(dict(span,source_key=key,speaker=speaker))
    return result


def select(response,entries):
    claims=response.get('claims') if isinstance(response,dict) else None
    if not isinstance(claims,list) or not 1<=len(claims)<=5:return None,['核心说法列表缺失或数量不合法']
    lookup={e['source_key']:e for e in entries};out=[];issues=[]
    for index,c in enumerate(claims):
        if not isinstance(c,dict):issues.append(f'claim{index}结构错误');continue
        keys=c.get('evidence_keys');confidence=c.get('confidence');claim=c.get('claim')
        valid=isinstance(keys,list) and bool(keys) and all(isinstance(k,str) and k in lookup for k in keys)
        valid=valid and len(keys)==len(set(keys))
        if not valid:issues.append(f'claim{index}未给有效唯一source_key，不能用子评论编号');continue
        selected=sorted((lookup[k] for k in keys),key=lambda e:e['start'])
        quote='...'.join(e['text'] for e in selected);actor=c.get('actor_quote');obj=c.get('object_quote')
        if type(confidence) not in (int,float) or not .9<=confidence<=1 or not isinstance(claim,str) or not claim.strip():
            issues.append(f'claim{index}说法或置信度未通过');continue
        if actor is not None and (not isinstance(actor,str) or {e['speaker'] for e in selected}!={actor}):
            issues.append(f'claim{index}发言者与所选原文标题不一致');continue
        if obj is not None and (not isinstance(obj,str) or not obj.strip() or obj not in quote):
            issues.append(f'claim{index}对象词不在所选实际证据中');continue
        out.append(dict(c,verified_evidence=quote,verified_speakers=[e['speaker'] for e in selected]))
    return (out if not issues else None),issues


def evidence_only(claims):
    """Selector prose is audit data, not a new source of summary facts."""
    return [{'evidence_keys':c['evidence_keys'],'verified_evidence':c['verified_evidence'],
             'verified_speakers':c['verified_speakers']} for c in claims]
