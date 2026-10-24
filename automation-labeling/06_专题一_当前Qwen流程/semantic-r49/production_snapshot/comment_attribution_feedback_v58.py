"""Staged repair feedback preserves failed evidence links, not approval.

Do not relax cross-turn binding gates. Give generation enough information to
avoid repeating the rejected attribution and to reread actual source entries.
"""
import comment_qualification_feedback_v57 as previous

GENERATION_INSTRUCTION=previous.GENERATION_INSTRUCTION+'''
每条评论轮次属于一个具体发言者。称“甲说X”时，X的每个属性都要有甲自己的原文证据。
不能把乙说的“刺眼”归甲，也不能将甲的所在地自动作为其所有发言的测量地点。
同名发言者在不同轮次说的属性并非自动同一对象；原文没有对象重述或可靠回复关系时，不硬加具体项目。
失败反馈中的failed_bindings仅是被拒的旧指向，不是认可的证据。到source_evidence_catalog核对每个键。
例如合成原文：甲说“我在南苑”；甲另轮说“晚上亮得刺眼”；乙说“北苑能看到吗”。
不能写“南苑、北苑均有严重光污染”。可保留“甲自述在南苑，并吐槽夜间刺眼；乙询问北苑能否看到。”
此处所在地是自述，夜间刺眼是甲的评价，乙是问询，不能新增两苑均受扰的确定结论。
摘要必须保留核心事实，但可省次要昵称；换成“有居民评价”仍不能把不同人的不同属性拼成一个人的结论。
禁止原样重返被拒的previous_prose；逐项修复失败归属或限定，新的摘要仍经同样独立核验。
'''

SYSTEM=previous.SYSTEM
verify=previous.verify
qualification_issues=previous.qualification_issues


def compact_feedback(checks):
    out=previous.compact_feedback(checks)
    if not isinstance(checks,list) or not isinstance(out,list):return out
    failed={c.get('prose_key'):c for c in checks if isinstance(c,dict) and c.get('accepted') is not True}
    for item in out:
        source=failed.get(item.get('prose_key'),{})
        links=source.get('raw_object_bindings')
        if isinstance(links,list):
            item['failed_bindings']=[{k:b[k] for k in ('object_quote','source_object_quote','object_source_key','attribute_source_key','generic_or_unresolved') if k in b}
                                     for b in links if isinstance(b,dict)]
    return out
