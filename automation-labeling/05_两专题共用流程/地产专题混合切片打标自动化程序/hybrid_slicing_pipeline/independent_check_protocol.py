"""Per-key protocol safety: incomplete unrelated checks cannot erase good ones."""
from collections import Counter

REPAIR_INSTRUCTION='''本轮仅补充缺失或重复的逐标签核验，不重做已经有效的其他标签决定。
逐一核对当前切片与字典定义，每个required_keys恰好一次，只返回{"checks":[...]}。
每项包含choice_key、status(supported/unsupported/ambiguous)、why、confidence；
supported还需direct_quote和可选object_quote，原文逐字引用。不靠其他标签已覆盖来排除不同事实。
证据不足返回ambiguous，不为凑齐数量编造事实或引文。'''


def merge_repair(checks, fixed, expected):
    safe, missing=select_checks(checks,expected)
    recovered, _=select_checks(fixed,missing)
    merged=safe+recovered
    return merged,set(expected)-{c['choice_key'] for c in merged}

def select_checks(checks,expected):
    if not isinstance(checks,list):return [],set(expected)
    items=[c for c in checks if isinstance(c,dict) and isinstance(c.get('choice_key'),str) and c['choice_key'] in expected]
    counts=Counter(c['choice_key'] for c in items)
    valid=[c for c in items if counts[c['choice_key']]==1 and c.get('status') in {'supported','unsupported','ambiguous'}
        and isinstance(c.get('why'),str) and c['why'].strip()]
    return valid,set(expected)-{c['choice_key'] for c in valid}
