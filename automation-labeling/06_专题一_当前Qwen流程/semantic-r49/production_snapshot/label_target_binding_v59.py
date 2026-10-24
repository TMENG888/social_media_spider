"""Staged independent object/property binding, with literal source references.

Not wired into the currently running frozen version. Schema checks do not
measure semantic accuracy. Rejected/uncertain labels are not auto-repaired.
"""
from prose_speaker_catalog import source_catalog
from structured_response_validation_v58 import issues as schema_issues
from comment_identity_protocol_v59 import obj,TEXT,KEYS,resolve

SYSTEM='''只独立审核指定标签的原文对象和属性是否匹配，不切片、不生成新标签、不改字典。
label_definition的完整路径和说明是业务要求。source_text是当前切片/完整评论；identity_context只帮助识别对象，不能补片外配置事实。
先找原文在讲的实际物理/业务对象，再找该对象的具体属性，不先看到风格/面积词就认同标签。
对象证据和属性证据可以在同一连续上下文不同句子，但必须唯一承接，不能跨项目或跨物理对象借用。
独立合成反例：原文“法式花园”，标签要求住宅精装风格：都是风格词但花园不是户内精装，object_supported=false。
独立合成反例：“三重礼序园林”，标签要求社区大门风格：不能用礼序通常经过大门推定大门，inference_free=false。
正例：“入口大门采用拱形门廊”，标签要求大门风格：对象明示入口大门，属性明示拱形门廊，可以有据通过。
“会所设25米泳池”，只支持泳池及25米这一属性，不支持整个会所宽25米。
字段设施/材料配置不同于施工工艺；设备品牌存在不代表设备质量经过检测；需按定义允许的具体配置或质量事实审核。
source_keys只选提供目录中的实际键。object_keys给对象所在范围，property_keys给属性所在范围；不得把解释推断作为证据。
comments中不同发言者的当前家庭状态不自动变为购房动机；本人态度、营销作者猜测客户和回复猜测必须区分。
业务对象同样要看整条路径：购房决策人之间关注点的分歧需要有不同决策者/意见的关系证据，个人担心延期交付不等于决策者意见分歧。
片区公共文化馆的规划问询是周边配套关注，不能只因为出现“规划”就套住宅总图规划关注；需区分片区、项目总图、户型三个尺度。
说明正文较通用时，仍必须满足路径所限定的对象及关系；示例不强制逐词出现，但不能把关键对象约束也当可有可无。
每个标签给supported/unsupported/uncertain、原文对象说明、属性说明及各独立判断。
supported仅在对象/属性/模态均有据且没有常识补全时可给。有效拒绝或低置信度不为填满标签而重试。
没有直接适用标签时允许不匹配，不用近似但定义不同的叶子冒充。'''

SCHEMA=obj({'status':{'type':'string','enum':['supported','unsupported','uncertain']},
    'actual_object':TEXT,'actual_property':TEXT,'object_keys':KEYS,'property_keys':KEYS,
    'object_supported':{'type':'boolean'},'property_supported':{'type':'boolean'},
    'modality_preserved':{'type':'boolean'},'inference_free':{'type':'boolean'},
    'why':TEXT,'confidence':{'type':'number','minimum':0,'maximum':1}})

def payload(text,definition,identity_context=''):
    return {'source_text':text,'source_catalog':source_catalog(text),
            'label_definition':definition,'identity_context':identity_context}

def verify(text,response):
    issues=schema_issues(response,SCHEMA)
    if issues:return False,issues
    if response['status']!='supported':return False,['标签目标核验未通过：'+response['why']]
    for field in ('object_supported','property_supported','modality_preserved','inference_free'):
        if response[field] is not True:issues.append('标签目标核验未通过：'+field)
    entries=source_catalog(text)
    for field in ('object_keys','property_keys'):
        if not resolve(response[field],entries):issues.append('标签目标原文证据未通过：'+field)
    if response['confidence']<.9:issues.append('标签目标核验置信度不足')
    return not issues,issues

def review(text,definition,identity_context,doc,runner):
    from bounded_structural_review_v59 import review as structural_review
    raw,calls,audit,errors=structural_review(SYSTEM,payload(text,definition,identity_context),SCHEMA,doc,
        '标签实际对象属性独立核验-v11.59',runner)
    if errors:return False,calls,audit,errors
    accepted,issues=verify(text,raw)
    return accepted,calls,audit,issues
