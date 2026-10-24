"""Ask for re-review when detail level is the sole claimed fact difference.

Never returns a merge or deletes a label. Partial overlaps, different measuring
objects and changing states need semantic adjudication, not text dedupe.
"""
import re


def issue(response):
    if not isinstance(response,dict):return None
    if response.get('same_object') is not True or response.get('same_fact') is not False:return None
    reason=str(response.get('why') or '')
    precision=re.search(r'模糊|笼统|概括性|定性描述|总数|事实精度|事实细节|宏观',reason)
    detail=re.search(r'具体(?:检测|数据|数量|户型|房间)|详细|量化|详实|明确.*数值',reason)
    distinct=re.search(r'完全不同|不同项目|不同户型(?:对象)?|不同时间|不同(?:施工|实施)状态|管道.{0,20}空鼓|空鼓.{0,20}管道',reason)
    if precision and detail and not distinct:
        return '事实不同的理由主要是概述与细节精度不同；须核同一事件是否重述，不能仅按详略保留重复标签'
    return None


INSTRUCTION='''同一事件的概述与细节数字可以是同一事实，不因一侧写“多处”、另一侧列出具体数量就当然不同。
先按全文身份与事件核对：两侧是否是同一套房、同一检测、同一缺陷。数量不一致、不同部位或时间状态仍须分开。
例如同一检测的总计30处与7+2+15+6处明细可能是总述/分项重述；不能只凭相加恰好30就确认同一事件。
标签可能在一片支持多个事实：若仅部分重叠且另有独立事实，不能删除整个标签，返回uncertain或different并具体写出独立事实。
开发商否认与业主投诉属于不同主张/状态，不强行合并。若概述已完整包含于详情且没有独立事实，选择详情侧保留。
重审仍须双侧原文证据及合法保留侧；不以减少重复数量作为结论目标。'''
