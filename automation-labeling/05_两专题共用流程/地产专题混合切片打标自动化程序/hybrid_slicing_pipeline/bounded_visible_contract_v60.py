"""Visible response contract for the model, not only gateway constrained decoding.

Grounding-key enums come from actual input catalogues. No semantic repair or
confidence increase is requested for a structurally valid rejection.
"""
import copy
from structured_response_validation_v58 import issues as schema_issues

INSTRUCTION = '''
必须阅读用户输入中的output_contract：它明确规定字段、类别枚举、原文证据键及允许空值。
只返回符合该合同的JSON。枚举只用合同中的真实值，不自己发明related等未允许类别。
why仅写一句最终证据理由，最多160字；禁止在任何字段输出内部思考、反复自问、候选推理或过程。
判断、理由和证据必须一致：不能分类无关却在理由承认属于研究范围。
原文证据键只从给定目录取；不用Evidence-1等自编键。真正不确定按允许结构如实返回，不默认高置信度。
只有指定字段可为空；要求非空对象键时应选择实际对象证据，不支持该标签则不选，而不是填无关键。'''


def contract(schema, payload):
    result = copy.deepcopy(schema)
    def keys(name):
        return [e['source_key'] for e in payload.get(name, [])
                if isinstance(e, dict) and isinstance(e.get('source_key'), str)]
    namespaces = {'comment_keys': keys('comment_catalog'),
                  'parent_identity_keys': keys('parent_catalog'),
                  'parent_relation_keys': keys('parent_catalog')}
    source = keys('source_catalog') or keys('primary_catalog')
    for name in ('source_keys', 'object_keys', 'property_keys', 'evidence_keys'):
        namespaces[name] = source
    def walk(node):
        if not isinstance(node, dict):
            return
        for name, child in node.get('properties', {}).items():
            if name == 'why':
                child['maxLength'] = 160
            if name in namespaces and namespaces[name] and child.get('type') == 'array':
                child['items'] = {'type': 'string', 'enum': namespaces[name]}
            walk(child)
        walk(node.get('items'))
        for branch in node.get('anyOf', []):
            walk(branch)
    walk(result)
    if 'all_applicable_labels' in payload:
        fields = result.get('properties', {}).get('labels', {}).get('items', {}).get('properties', {})
        for key in ('source_keys', 'object_keys'):
            if key in fields:
                fields[key]['minItems'] = 1
    return result


def review(system, payload, schema, doc, phase, runner):
    calls, audit = [], []
    requested = contract(schema, payload)
    original = dict(copy.deepcopy(payload), output_contract=requested)
    current = original
    for attempt in range(2):
        raw, metrics = runner.call(system + INSTRUCTION, current, doc,
            phase if not attempt else phase + '-结构恢复', response_schema=requested)
        calls.append(metrics)
        if metrics.get('status') != 'success':
            errors = ['独立核验API未成功']
            audit.append({'raw_response': raw, 'protocol_issues': errors})
            return None, calls, audit, errors
        errors = schema_issues(raw, requested)
        audit.append({'raw_response': copy.deepcopy(raw), 'protocol_issues': errors})
        if not errors:
            return raw, calls, audit, []
        current = dict(original, previous_response=raw, protocol_issues=errors,
                       repair_instruction='只修实际结构违规，按可见合同返回最终JSON；不默认信心，不输出内部过程。')
    return None, calls, audit, errors
