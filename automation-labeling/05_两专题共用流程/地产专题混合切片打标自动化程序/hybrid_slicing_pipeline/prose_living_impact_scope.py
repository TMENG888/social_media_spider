"""Narrow explicit living-impact omission guard, not semantic accuracy proof.

Only source-stated limited/no living impact triggers this check. It never
invents impact, assigns projects, selects tags or changes slice boundaries.
Independent evidence and speaker checks remain required.
"""
import re

SOURCE=re.compile(r'(?:不(?:至于|会|太|怎么|大)?影响|未影响)(?:日常)?(?:生活|居住|休息|睡眠)')
SUMMARY=re.compile(r'(?:不(?:至于|会|太|怎么|大)?影响|未影响)(?:日常)?(?:生活|居住|休息|睡眠)'
    r'|(?:生活|居住|休息|睡眠).{0,6}(?:不受影响|无影响|影响不大|影响有限|未受影响)')


def issues(source,prose):
    if not isinstance(source,str) or not isinstance(prose,str) or not prose:return []
    matches=list(SOURCE.finditer(source))
    if not matches or SUMMARY.search(prose):return []
    evidence=[source[max(0,m.start()-18):min(len(source),m.end()+18)] for m in matches]
    return [{'reason':'摘要遗漏原文明示的生活影响限定；须保留有限/无影响及相应对象，不只概括响声或恐惧。',
             'source_quote':q,'accepted':False} for q in evidence]
