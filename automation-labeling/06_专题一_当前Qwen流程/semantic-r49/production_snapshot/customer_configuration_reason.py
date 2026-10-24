"""Flag product-description evidence misused as personal purchase attention.

An audit trigger, never a replacement label or a first-person requirement.
Comments can express personal judgement without the literal word 'I'.
"""
import re


def issue(tag, quote, reason):
    if tag.get('l1')!='客户' or tag.get('l3')!='购房关注点':return None
    quote=str(quote or '');reason=str(reason or '')
    # Actual judgements/questions/choices are not rejected for missing pronouns.
    personal=re.search(r'关注|想买|想选|考虑|纠结|看中|看重|在意|喜欢|不喜欢|满意|不满意|嫌|太大|太小|太贵|贵了|便宜|适合我|适合我们|预算|不够|够用|担心|能否|怎么|如何|吗|[?？]',quote)
    if personal:return None
    configuration=re.search(r'洋房|精装交付|豪装交付|低密|\d+\s*室\d+\s*厅|套房设计|层高|得房率|南向|衣帽间|户型配置',quote)
    reason_personal=re.search(r'本人.{0,20}(?:关注|选择|意向|提问)|自述.{0,20}(?:关注|选择)|明确.{0,12}(?:购房关注|选择过程|购买意向)|表达.{0,12}(?:关注|偏好)',reason)
    if configuration and not reason_personal:
        return '客户购房关注点仅以房屋配置描述支持，尚无本人关注/选择过程证据；须按客户定义独立复核，不能套用同名产品标签定义'
    return None


INSTRUCTION='''核对当前标签完整一级路径及定义，而不只看末级同名词。
“客户/购房决策/购房关注点/精装”需要真实发言者的关注或选择过程；卖方“精装交付”只说明产品装修状态。
“四居洋房、4室2厅3卫、三套房设计”不自动证明客户关注物业形态或户型。
真实评论“这个户型太大了”“精装够用吗”“更喜欢洋房”可表达本人判断或提问，不要求必须有“我”字。
不要为填满客户标签将产品广告变成购房者本人态度；产品配置标签仍按它自身定义另行判断。'''
