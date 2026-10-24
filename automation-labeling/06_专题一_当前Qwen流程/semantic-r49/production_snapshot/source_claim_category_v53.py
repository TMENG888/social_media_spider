"""Staged source-only definition audit; never treat model rationale as evidence.

Used by v53 production definition review. Flags require independent
definition review; they do not select replacement tags or slice boundaries.
"""
import re

def issue(tag,quote,reason='',object_context=''):
    quote=str(quote or '')
    if tag.get('l1')=='客户' and tag.get('l3')=='购房关注点':
        # No first-person prerequisite: judgements and genuine questions count.
        personal=re.search(r'我(?:们)?(?:想|在|正|最近|考虑|看|选|买|纠结|觉得|关注|喜欢|预算)|本人|我们家|我家|看重|在意|想买|想选|纠结|更喜欢|不喜欢|满意|不满意|太贵|太大|太小|够用|不够|担心|能否|如何|怎么|吗|[?？]',quote)
        configuration=re.search(r'精装|装标|装修|智慧家居|全屋智能|智能系统|配了|配置|施工|工艺|静音系统|客群|产品定位|公区|大堂|视觉冲击|氛围感',quote)
        if configuration and not personal:
            return '原文仅介绍产品配置/适配客群，未明确本人关注或选择；模型理由引用客户定义不能代替原文行为证据'
    if tag.get('l1')=='服务' and tag.get('l2')=='销售服务':
        experience=re.search(r'销售(?:说|告诉|承诺|答复|顾问)|置业顾问|售楼处|售前|咨询|到访|签约|合同|承诺|销售清单|交付清单|宣传(?:承诺|口径)|兑现|货不对板',quote)
        configuration=re.search(r'装标|精装|装修|配置|配了|品牌|智能系统|厨电|卫浴',quote)
        if configuration and not experience:
            return '原文仅是产品配置介绍，未说明售前咨询/到访/签约/销售承诺经历；不能把所有配置介绍推定为销售承诺'
    if tag.get('l1')=='产品' and tag.get('l3')=='厨房' and tag.get('l4')=='油烟机+燃气灶':
        if re.search(r'厨电|厨房电器|厨房设备',quote) and not re.search(r'抽油烟机|油烟机|燃气灶|煤气灶|灶具',quote+' '+str(object_context or '')):
            return '仅泛称厨电或厨房设备，不证明具体油烟机/燃气灶对象；不能由设备大类推断所包含的具体设备'
    return None

INSTRUCTION='''支持理由不是原文证据。重复定义中的“本人关注”不能证明发言者实际表达关注。
客观楼盘对比、适配互联网客群、分析精装逻辑不自动属于客户购房关注点；须指出真实发言者关注/选择/判断的原文。
不强制出现“我”：评论“精装够用吗”“更喜欢这个户型”可以成立，但客观配置介绍另按产品定义核查。
配置品牌、装标介绍不自动为销售承诺；服务标签须指出咨询、到访、签约、承诺或兑现的实际经历证据。
“完成空调、新风和吊顶后净高仍足够”可能是装修条件或说明，不能未经声称性质核验就写成已配置/已交付。
原文明确项目配置、销售承诺、实际交付是不同事实层级，保留原文声称，不升级。'''
INSTRUCTION+='''\n公区的视觉冲击/豪宅氛围仅描述产品效果，不自动证明客户本人购房关注。
厨电、厨房设备等上位类别不证明具体油烟机或燃气灶存在；有明确其中一种设备的事实可按合并标签定义核查，不额外要求同时写出另一设备。'''
