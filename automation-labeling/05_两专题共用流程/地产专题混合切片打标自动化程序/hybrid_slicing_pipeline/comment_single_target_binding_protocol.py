"""Staged program-owned singleton assertion target; not yet production-wired.

Never retrofit an old response by silently changing its model-authored assertion.
The new protocol requires explicit actual target keys on each source binding.
"""
import copy
import comment_fragment_entailment as entailment


INSTRUCTION='''
本请求只有一个prose_catalog目标。程序掌握该目标的完整原样text，禁止另造assertion_quote，
禁止用省略号拼接摘要中的不连续词。checks中prose_key精确指向该目标，审核的是整个目标text。
object_bindings中每项也须返回同一prose_key，明确object_quote、source_object_quote、
object_source_key、attribute_source_key、attribute_quote、generic_or_unresolved。
每个具体对象都必须实际出现在目标text中，原文对象及属性仍须逐字引用有效source_key。
两条路线共用“均经过四个红绿灯”的摘要，可为每条路线分别绑定各自原句，
但不生成不存在的“去路线A...经过红绿灯”摘要引文。不能把同一个次数误说成两路线总和。
泛指对象可以null，但明确项目/地块不能伪装泛指。同一昵称再次发言是另一次评论轮次。
程序只确定待审核目标文本，绝不替模型判定关系、模态、限定或置信度。
'''

# Replace, never append to the contradictory old assertion-quote schema.
_semantic_system=entailment.SYSTEM.removesuffix(entailment.bindings.INSTRUCTION)
_semantic_system=_semantic_system.replace('"assertion_quote":"当前text逐字表述",','')
_semantic_system=_semantic_system.replace(
    'assertion_quote必须是当前待审text里逐字存在的被审核表述，不改写成它没说过的断言。',
    'prose_key必须指向当前唯一待审text，不替换成另一个命题；完整text由程序按该键持有。')
SYSTEM=_semantic_system+INSTRUCTION


def resolve(fragment, response):
    if not isinstance(response,dict):return None,['单目标核验响应不是对象']
    checks=response.get('checks');bindings=response.get('object_bindings')
    key=fragment['prose_key'];issues=[]
    if not isinstance(checks,list) or len(checks)!=1 or not isinstance(checks[0],dict):
        return None,['单目标核验未返回唯一check']
    if checks[0].get('prose_key')!=key:issues.append('check目标键与实际目标不符')
    if 'assertion_quote' in checks[0] and checks[0]['assertion_quote']!=fragment['text']:
        issues.append('新协议不得返回另造或不完整的审核命题引文')
    if not isinstance(bindings,list) or not bindings:
        return None,issues+['新协议缺少逐项对象来源绑定']
    for binding in bindings:
        if not isinstance(binding,dict):issues.append('对象绑定不是对象');continue
        if binding.get('prose_key')!=key:issues.append('对象绑定缺失或错用实际目标键')
        if 'assertion_quote' in binding:
            issues.append('对象绑定仍使用模型自造命题引文，须按新键协议重新核验')
    if issues:return None,issues
    resolved=copy.deepcopy(response)
    resolved['checks'][0]['assertion_quote']=fragment['text']
    for binding in resolved['object_bindings']:
        binding['assertion_quote']=fragment['text']
    return resolved,[]


def verify(fragment, source_catalog, response):
    resolved,issues=resolve(fragment,response)
    if issues:return False,[{'accepted':False,'issues':issues,'verification_scope':'单实际目标绑定协议'}]
    okay,audit=entailment.verify_one(fragment,source_catalog,resolved)
    for item in audit:
        item['target_text_owner']='程序按实际唯一prose_key回填，不生成摘要或改写模型结论'
        item['raw_object_bindings']=copy.deepcopy(response['object_bindings'])
    return okay,audit
