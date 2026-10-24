"""Validate the limited JSON-schema surface used by the staged protocols.

No semantic approval or confidence threshold lives here. A valid rejection and
a valid low-confidence response must not become a format-repair request.
"""
import math


def issues(value, schema, path='$'):
    if 'anyOf' in schema:
        if any(not issues(value, branch, path) for branch in schema['anyOf']):
            return []
        return [path + ': 不符合任何允许结构']
    kinds = schema.get('type', [])
    kinds = [kinds] if isinstance(kinds, str) else kinds
    valid = {'object': isinstance(value, dict), 'array': isinstance(value, list),
             'string': isinstance(value, str), 'null': value is None,
             'boolean': type(value) is bool, 'integer': type(value) is int,
             'number': type(value) in (int, float) and math.isfinite(value)}
    if kinds and not any(valid.get(kind, False) for kind in kinds):
        return [path + ': 数据类型不符合请求结构']
    out = []
    if 'enum' in schema and value not in schema['enum']:
        out.append(path + ': 不在允许枚举中')
    if isinstance(value, dict):
        props = schema.get('properties', {})
        for key in schema.get('required', []):
            if key not in value:
                out.append(path + '.' + key + ': 缺少必填字段')
        if schema.get('additionalProperties') is False:
            out += [path + '.' + str(key) + ': 未允许字段' for key in value if key not in props]
        for key, child in props.items():
            if key in value:
                out += issues(value[key], child, path + '.' + key)
    elif isinstance(value, list):
        if len(value) < schema.get('minItems', 0):
            out.append(path + ': 数组不足最少项数')
        for i, child in enumerate(value):
            out += issues(child, schema.get('items', {}), path + '[' + str(i) + ']')
    elif isinstance(value, str):
        if len(value.strip()) < schema.get('minLength', 0) or len(value) > schema.get('maxLength', float('inf')):
            out.append(path + ': 文本长度违反请求结构')
    elif type(value) in (int, float):
        if value < schema.get('minimum', -float('inf')) or value > schema.get('maximum', float('inf')):
            out.append(path + ': 数值超出请求范围')
    return out
