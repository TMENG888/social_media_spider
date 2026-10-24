"""Narrow affirmative inference alarms, not label grants.

Matching an explicit fact to a dictionary definition ('belongs to ... therefore
supported') is not industry inference. Negating an inference is not making it.
Scope, quantity and source-evidence checks remain independent prerequisites.
"""
import re


def assumption_reason(reason):
    reason=str(reason or '')
    reason=re.sub(r'(?:无需|无须|不需要|不必|并非|不是|未|不依赖|不能|禁止|避免|没有)'
                  r'(?:(?:额外|进行|借助|基于|按照|根据|行业常识|行业惯例|再|作)\s*){0,3}'
                  r'(?:推断|推测|隐含的)', '[否定表述]', reason)
    return bool(re.search(r'通常(?:包含|指|涵盖|暗示)|在房地产语境下对应|隐含的|推(?:断|测)|'
                          r'(?:根据|基于|按照|依靠)(?:行业惯例|行业常识)|'
                          r'取主要数值|数量为1.*非数量|明确存在1个.*非数量',reason))
