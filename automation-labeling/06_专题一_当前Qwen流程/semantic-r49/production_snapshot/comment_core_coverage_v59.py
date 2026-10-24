"""Staged whole-comment semantic coverage, not slicing into output rows.

Every original evidence key is classified independently, so a reply-only
summary cannot hide the primary concrete event behind a coverage boolean.
"""
from prose_speaker_catalog import source_catalog
from comment_identity_protocol_v59 import obj,TEXT
from structured_response_validation_v58 import issues as schema_issues

SYSTEM='''只独立核完整评论摘要的核心覆盖，不重写摘要，不决定标签，不把评论拆成输出行。
source_text是主评论及全部回复，summary是待核文本。source_catalog是原文证据目录，不是最终切片。
每个source_key恰好分类一次：具体事实、评价、提问、附和、营销、无关、未读媒体。importance取major/minor/noncore。
major是会改变该讨论主要事实、对象、态度或程度限定的说法，不等于穷举所有次要数字或昵称。
主评论给具体事件、回复只说“附近人才懂”时，主要事实是事件，不能只保留回复附和。
独立合成例：父评论“雨后用移动设备清积水”，回复“附近居民才懂”。摘要仅写“居民了解生活经验”遗漏清积水事件，应拒绝核心覆盖。
反例：父评只是赞同，回复才给具体设施问题，应以回复问题为核心；不机械认为父评一定最重要。
范围限定属于核心：甲西侧和乙北侧噪音相近，不得摘要为整个甲乙噪音都相近。室外听到、室内听不到应保留场景差异，不得写完全没有噪音。
每个major项逐项判断摘要是否完整覆盖；非核心附和或次要数字允许省略。
captures_primary_points仅在全部major内容均有忠实覆盖时为true；不要求摘要复述整篇，不把次要细节省略当误判。
source_key选择实际原文键，不生成改写引文，不输出长内部反思。置信度不足如实给出。'''

def schema(entries):
    item=obj({'source_key':{'type':'string','enum':[e['source_key'] for e in entries]},
        'role':{'type':'string','enum':['具体事实','评价','提问','附和','营销','无关','未读媒体']},
        'importance':{'type':'string','enum':['major','minor','noncore']},
        'summary_covers':{'type':'boolean'},'why':TEXT})
    return obj({'source_roles':{'type':'array','items':item,'minItems':len(entries)},
        'captures_primary_points':{'type':'boolean'},'why':TEXT,
        'confidence':{'type':'number','minimum':0,'maximum':1}})

def verify(source,summary,response):
    entries=source_catalog(source);errors=schema_issues(response,schema(entries))
    if errors:return False,errors
    keys=[x['source_key'] for x in response['source_roles']]
    if len(keys)!=len(entries) or set(keys)!={e['source_key'] for e in entries}:
        errors.append('核心覆盖未恰好分类全部原文证据键')
    if not summary:errors.append('摘要为空不能证明覆盖')
    majors=[x for x in response['source_roles'] if x['importance']=='major']
    if not majors:errors.append('未识别具体主要内容，需独立核是否仅无效内容')
    if any(not x['summary_covers'] for x in majors):errors.append('摘要遗漏已识别的主要事实/限定')
    if not response['captures_primary_points']:errors.append('全文核心覆盖未通过')
    if response['confidence']<.9:errors.append('全文核心覆盖置信度不足')
    return not errors,errors

def review(source,summary,doc,runner):
    from bounded_structural_review_v59 import review as bounded
    entries=source_catalog(source)
    raw,calls,audit,errors=bounded(SYSTEM,{'source_text':source,'source_catalog':entries,'summary':summary},
        schema(entries),doc,'完整评论逐原文核心分类覆盖-v11.59',runner)
    if errors:return False,calls,audit,errors
    accepted,errors=verify(source,summary,raw)
    return accepted,calls,audit,errors
