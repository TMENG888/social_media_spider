"""The authorized VOC-0377 exception; no relaxation of other labels."""
import re

VERSION = 'VOC-0377-club-gym-20261011'
INSTRUCTION = ('记录社区会所内部的健身房或健身器械配置。只要原文明示会所内设有健身房，即打健身房器械标签，'
    '无需具体器械名称、数量或设施细节；例如“会所内部功能空间有：书吧、会客厅、游泳池、健身房、疗愈瑜伽室”。'
    '原文明确会所配置健身器械也适用。会所外部、周边健身房、工作人员泛谈器械、仅运营活动，'
    '不能据此标注；否定或疑问不得写成已配置，规划或宣传保留原文限定。不推断器械品牌、数量或开放状态。')

def enabled(tag):
    return tag.get('tag_id') == 'VOC-0377' and '无需具体器械' in tag.get('instruction', '')

def relation_issue(text, own_end, attr_start):
    """Require an explicit containment/configuration assertion, not two nouns."""
    bridge=text[own_end:attr_start]
    if re.search(r'工作人员|员工|讲解|谈论|行业|趋势|科普|课程|讲座|外面|附近|周边|旁边|另一个|其他项目',bridge):
        return '健身房/器械不是明确的会所内部配置，不能只靠共现补标'
    if not re.search(r'设有|设立|设置|配备|配有|配置|包括|包含|内有|内设|内部|内置|功能|拥有|打造|规划|将设|的|有',bridge):
        return '尚未明确健身房/器械属于会所内部配置，送模型核验'
    return None

def obsolete_refusal(reason):
    """Only the old equipment-list requirement expires, not object conflicts."""
    return bool(re.search(r'器械|设备',reason) and re.search(r'未提及|未描述|未明确|没有|缺少|不满足|不证明|未出现|仅提及|仅.*健身房',reason)
        and not re.search(r'外部|周边|公园|架空层|其他项目|对象不|对象.*不匹配|不同.*对象|不同.*空间',reason))
