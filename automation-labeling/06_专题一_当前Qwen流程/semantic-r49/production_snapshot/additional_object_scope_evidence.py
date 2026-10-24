"""Conservative object-scope review triggers; not tag selection rules.

Triggers quarantine an unsupported inference for evidence review; they never
invent a replacement tag, rewrite source numbers or decide slice boundaries.
"""
import re


def scope_issue(tag, quote, reason):
    quote=str(quote or '');reason=str(reason or '')
    room=tag.get('l3');attribute=tag.get('l4')
    if tag.get('l1')=='产品' and tag.get('l2')=='公区' and room=='景观':
        external=re.search(r'生态走廊|滨河水岸|市政公园|城市公园|北眺|南望|周边公园|毗邻.{0,12}公园',quote)
        internal=re.search(r'(?:小区|社区|园区|项目)(?:内|内部|内部的)|红线内|自建景观|自建公园',quote)
        if external and not internal:
            return '生态走廊/市政或周边景观未确认位于项目内部，不能把外部环境的风格或面积写为社区公区景观'
    if tag.get('l1')=='客户' and attribute=='近期关注项目' and re.search(r'探盘|领取资料|领资料',quote):
        if not re.search(r'我|本人|正在看|最近在看|纠结|考虑|选择|打算|想买|想入手',quote):
            return '探盘或推广标题未表达本人项目关注/选择过程，不能据内容标题补客户画像'
    if room in {'客厅','主卧','次卧','餐厅'} and attribute=='朝向' and '四面宽' in quote:
        explicit=re.search(re.escape(room)+r'[^，。；]{0,12}(?:朝|向|南|北|东|西)',quote)
        if not explicit:
            return '整体四面宽未逐个指明房间朝向，不能按常见户型补出具体房间朝向'
    if tag.get('l1')=='土地' and tag.get('l2')=='板块' and attribute=='板块档次':
        if re.search(r'豪宅|顶豪|高端|刚需',quote) and not re.search(r'板块|片区|区域|聚集区|集聚区',quote):
            return '当前档次证据未确立板块范围，不能将单项目宣传扩大为整个板块档次'
    if tag.get('l1')=='土地' and tag.get('l2')=='地块' and attribute=='层高':
        if not re.search(r'规划|设计|地块条件|标准层|楼栋|楼层',quote):
            return '房屋层高未确立地块规划或设计条件及适用范围，土地规划属性待核'
    if attribute=='社区卫生服务中心' and '社区服务' in quote:
        if not re.search(r'卫生|医疗|诊疗|社区医院|卫生院',quote):
            return '社区服务机构未说明卫生或医疗性质，不能擅自确定为社区卫生服务中心'
    if attribute=='外立面性能' and re.search(r'听不到|听不见|隔音|隔绝|噪音',quote):
        if not re.search(r'外立面|外墙|幕墙|玻璃|门窗|墙体|墙面|窗户',quote):
            return '室内外听感差异未明确归因外立面设施或性能，不能据结果补构造性能'
    if attribute in {'当前居住区域','当前居住楼盘'}:
        if re.search(r'之前|以前|曾经|曾住|小时候|高中|大学',quote):
            if not re.search(r'现在|目前|如今|仍(?:然)?住|一直住|住了.{0,5}年了',quote):
                return '证据只自述历史居住经历，未确认当前居住现状'
    if re.search(r'通常[^，。；]{0,20}(?:指|涵盖|包含|意味着)|结合常识|根据常识',reason):
        return '支持理由使用常识或通常情况补足，须以原文明确对象属性替代推断'
    return None
