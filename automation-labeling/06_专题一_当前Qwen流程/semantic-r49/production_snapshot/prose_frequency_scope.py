"""Review trigger for newly invented daily frequency denominators.

This does not estimate frequency or rewrite numbers. Only a numeric count with
an explicit daily unit in the draft is checked; other units remain semantic
review work. Preserve an issue rather than assume a zero frequency.
"""
import re


def issues(source,prose):
    source=str(source or '');prose=str(prose or '');out=[]
    counts=[]
    for match in re.finditer(r'(\d+(?:\.\d+)?)\s*(?:来|余|多)?\s*次\s*(?:/\s*天|每天|每日|一天)',prose):
        counts.append(match.group(1))
    for match in re.finditer(r'(?:每天|每日|一天)[^，。；！？]{0,16}?(\d+(?:\.\d+)?)\s*(?:来|余|多)?\s*次',prose):
        counts.append(match.group(1))
    for count in dict.fromkeys(counts):
        number=r'(?<![\d.])'+re.escape(count)+r'(?![\d.])\s*(?:来|余|多)?\s*次'
        # Numeral conversion and invented counts belong to other grounding checks.
        if not re.search(number,source):continue
        before=r'(?:每天|每日|一天)[^，。；！？]{0,20}?'+number
        after=number+r'\s*(?:/\s*天|每天|每日|一天)'
        # Both the count and denominator must be in the same local fact.
        if not re.search(before,source) and not re.search(after,source):
            out.append('摘要将'+count+'次补为每日频率，原文对应次数未明示每日分母；不能借另一事件的一天次数')
    return out
