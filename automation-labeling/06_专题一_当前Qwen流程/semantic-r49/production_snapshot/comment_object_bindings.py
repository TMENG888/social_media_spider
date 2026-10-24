"""Literal turn-local object/attribute grounding, not comment output splitting.

The stored flat thread has no reliable reply-to edges. A speaker returning later
is a new turn; equal nicknames do not prove continuity of the discussed object.
"""
import re
from focused_summary_references import catalog


def source_catalog(source):
    headers=[m.start() for m in re.finditer(r'【(?:父评论|子评论\d*)｜[^】]+】',source)]
    entries=catalog(source)
    for e in entries:
        e['turn_id']=sum(start<=e['start'] for start in headers)
    return entries


def verify(fragment, entries, bindings):
    lookup={e['source_key']:e for e in entries};issues=[]
    if not isinstance(bindings,list) or not bindings:
        return ['对象事实关联审核缺失，不能仅凭四个布尔值通过']
    for b in bindings:
        if not isinstance(b,dict):
            issues.append('对象关联结构无效');continue
        assertion=b.get('assertion_quote');obj=b.get('object_quote')
        object_key=b.get('object_source_key');attribute_key=b.get('attribute_source_key')
        source_obj=b.get('source_object_quote',obj)
        attribute=b.get('attribute_quote')
        if not isinstance(assertion,str) or not assertion.strip() or assertion not in fragment:
            issues.append('关联命题不是实际摘要逐字文本');continue
        if not isinstance(attribute_key,str) or attribute_key not in lookup or not isinstance(attribute,str) or not attribute.strip() or attribute not in lookup[attribute_key]['text']:
            issues.append('属性证据未定位到实际原文');continue
        if obj is None:
            if object_key is not None or b.get('generic_or_unresolved') is not True:
                issues.append('泛指对象必须明确标识且不能附会具体对象证据')
            continue
        if (not isinstance(obj,str) or not obj.strip() or obj not in assertion
                or not isinstance(object_key,str) or object_key not in lookup
                or not isinstance(source_obj,str) or not source_obj.strip() or source_obj not in lookup[object_key]['text']):
            issues.append('明确对象不在摘要及所选对象原文中');continue
        object_entry=lookup[object_key];attribute_entry=lookup[attribute_key]
        if (object_entry['turn_id']!=attribute_entry['turn_id']
                and obj not in attribute_entry['text'] and source_obj not in attribute_entry['text']):
            issues.append('不同评论轮次的属性未重述对象，缺少可靠回复关系，不能归给该具体对象')
    return issues


INSTRUCTION='''
在返回JSON根级（与checks并列）返回object_bindings数组，每条实际命题均明确对象和属性原文，不只返回支持布尔值。
每项包含assertion_quote（当前摘要逐字命题）、object_quote（命题里的逐字具体对象或null）、
source_object_quote（原文中的对应对象逐字文本或null）、object_source_key（包含该对象的实际原文键或null）、attribute_source_key、attribute_quote（该键内逐字事实）、generic_or_unresolved。
object_quote必须实际存在于assertion_quote；原文表达不同可用source_object_quote，但二者必须同一对象，不能换成另一个地块或发言者。
所有quote必须逐字连续，不能插入省略号、拼接两处文本或改写证据；长事实可分别列多个关联项。
明确项目/地块/方向对象必须给object_quote及object_source_key，不能伪装泛指以绕过对象审核。
只有摘要本身未指定具体对象的泛指命题才用null和generic_or_unresolved=true。
turn_id由程序按原始评论标题计算。同一发言者再次回复是另一轮，不证明同一对象。
对象与属性处在不同turn_id且属性原句未重述该对象时，平铺评论没有可靠回复关系，判uncertain。
例如甲说A北侧可能较好，乙说“最北侧也吵”，不能生成“A北侧也吵”；可保留“另一评论者称北侧也吵”，不要猜指代。
同一轮连续句可用上句对象承接下句属性，不要求每句重复对象；仍检查中途有无对象切换。
'''
