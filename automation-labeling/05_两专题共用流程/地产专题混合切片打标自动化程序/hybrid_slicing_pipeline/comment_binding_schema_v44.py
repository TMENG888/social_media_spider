"""Staged explicit root binding schema; production v11.43 remains unchanged."""
import comment_single_target_binding_protocol as protocol
import relative_comparison_guard_v45 as relative_guard


# Retain semantic restrictions but replace the only incomplete JSON example.
_before=protocol.SYSTEM.split('返回{"checks":',1)[0]
SYSTEM=_before+'''
唯一返回结构如下；两个根键checks和object_bindings必须同时返回，不能只写checks：
{"checks":[{"prose_key":"唯一实际目标键","status":"supported/unsupported/uncertain",
"source_keys":["实际原文键"],"object_binding_supported":true,"relation_supported":true,
"modality_preserved":true,"qualifiers_preserved":true,"why":"简短实际依据或错误","confidence":0.95}],
"object_bindings":[{"prose_key":"同一个实际目标键","object_quote":"待审text中的对象名词或null",
"source_object_quote":"原文中对应对象的逐字名词或null","object_source_key":"实际对象来源键或null",
"attribute_source_key":"实际属性来源键","attribute_quote":"该来源键的连续逐字事实",
"generic_or_unresolved":false}]}。
object_quote是对象名词，不是“驱鸟炮优于魔音”等整段结论或属性；属性放attribute_quote。
object_quote不为null时generic_or_unresolved必须为false；泛指对象为null时必须true，绝不是null。
具体项目、地块和发言者不得伪装泛指对象绕过原文绑定。每个实际对象均须有绑定，不能漏整组。
supported也必须有完整object_bindings；证据不支持或不确定则如实返回，不制造绑定。
'''+protocol.INSTRUCTION+'''
未体验和相对选择必须保留：原文“未听过，二选一也许A好一点”，
可概括“回复者未体验，仅倾向在两者中选A”，不能写“A优于B/认为A更好”而去掉未体验与也许。
“我觉得频率少了”可写“评论者认为频率减少”，但不能变成已经实测减少。
讨论不同地块的“北侧”不一定相同；看不到可靠回复关系时保留不同发言，不串成对某一地块的确定反驳。
这是完整命题的关系及限定核验，不因原文还有未概括的其他内容而拒绝当前有据片段。
同一发言轮的相邻句共同限定同一比较；未听过在前句、二选一也许在后句时不能漏掉前句限定。不得借同昵称另一轮的话。
原文“家里”可概括“家中/室内”，“小区里遛弯”可概括“在小区遛弯”；允许忠实同义表达，不仅因未出现原样词拒绝。
若概括室外则仍须保留具体活动范围及声音程度，不能删“频率不高、声音不大”。
why只写最终依据，不输出思考过程或与status矛盾的论述。
绑定对象只写名词，不包括共享动作：摘要“前往南外环和新河路均有三个路口”，对象填“南外环”“新河路”，不能填摘要未逐字出现的“前往新河路”。
“该地/此处/这里/这一带”且原文无具体名时属于泛指：object_quote=null、source_object_quote=null、object_source_key=null、generic_or_unresolved=true；属性仍需实际原文键。不能伪造明确名称。
“相对倾向”也必须保留未体验：原文未听过某声音，仅二选一猜可能较好，摘要不能只写倾向而丢“未听过/未体验”。
'''


def verify(fragment,source_catalog,response):
    bindings=response.get('object_bindings') if isinstance(response,dict) else None
    if isinstance(bindings,list):
        for binding in bindings:
            if not isinstance(binding,dict):continue
            if type(binding.get('generic_or_unresolved')) is not bool:
                return False,[{'accepted':False,'issues':['泛指状态必须为真正布尔值，不得null或缺失']}]
            if binding.get('object_quote') is not None and binding['generic_or_unresolved'] is not False:
                return False,[{'accepted':False,'issues':['明确对象不得伪装为泛指以绕过关联']}]
    okay,audit=protocol.verify(fragment,source_catalog,response)
    if okay:
        issues=relative_guard.issues(fragment,source_catalog,response)
        if issues:
            for a in audit:
                a['accepted']=False;a.setdefault('issues',[]).extend(issues)
            okay=False
    return okay,audit
