"""Conservative decision consistency checks; never delete a semantic label.

A failed check requests independent re-review. Genuine uncertain/different
facts stay intact; no phrase in a rationale is itself a deletion instruction.
"""
import re


def decision_issue(raw):
    if not isinstance(raw, dict):
        return '决定不是JSON对象'
    same = raw.get('same_object') is True and raw.get('same_fact') is True
    different = raw.get('same_object') is False or raw.get('same_fact') is False
    side = raw.get('keep_side')
    reason = str(raw.get('why') or '')
    if not same and side in {'A', 'B'}:
        return '未认定同对象同事实，却指定单侧保留；不同事实或不确定时应保留双方'
    if different and re.search(r'(?:故|因此|只|仅|应|建议)\s*保留\s*[AB]\s*(?:侧|方)', reason, re.I):
        return '不同事实结论与理由中的单侧保留建议矛盾'
    if same and re.search(r'不同事实|不重复|并非同一事实|不能归并', reason):
        return '同事实结论与理由中的不归并判断矛盾'
    return None


REVIEW = '''上一决定的字段与理由不一致，尚未通过，不沿用它的结论。
请重新独立判断同一对象及当前标签对应的同一事实。
整体概述与详情可能重述同一设计意象；措辞抽象与具体本身不证明事实不同。
若概述根本没有足够依据支持此标签，说明证据不足并返回不确定，不把“错误标签”伪装成“不同事实”。
同事实必须给出两侧有效证据编号及保留侧；不同事实或不确定时keep_side必须null，并保留双方。
仅依据本次输入，不为消除重复强行认定相同。返回完整规定JSON。'''
