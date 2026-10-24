"""Isolate schema field identities; disallow null prose with asserted facts."""
import json
import delivery_v61 as current
from comment_identity_protocol_v59 import obj, TEXT, KEYS

VERSION = 'delivery-v11.62-disjoint-evidence-contract-prose-consistency-20261010'
_contract = current.current.visible.contract


def contract(schema, payload):
    # deepcopy preserves alias identity: shared KEYS objects were overwritten
    # first by COMMENT enum, then PARENT enum. JSON schema fields are independent.
    independent = json.loads(json.dumps(schema, ensure_ascii=False))
    return _contract(independent, payload)


def generation_schema():
    claim = obj({'text': TEXT, 'source_keys': KEYS})
    def branch(prose, claims):
        return obj({'prose': prose, 'claims': claims,
                    'confidence': {'type': 'number', 'minimum': 0, 'maximum': 1},
                    'why': TEXT})
    return {'anyOf': [
        branch({'type': 'string', 'minLength': 1},
               {'type': 'array', 'items': claim, 'minItems': 1}),
        branch({'type': 'null'}, {'type': 'array', 'enum': [[]]})]}


def activate():
    current.activate()
    pipeline = current.current.integrated
    current.current.visible.contract = contract
    pipeline.prose.generation_schema = generation_schema
    pipeline.prose.GENERATE += '''
output_field=practice表示输出“具体产品做法”，summary表示输出“观点摘要”。
prose是最终要交付的转写文本，claims只是它的原文追溯清单，不能把文案只放claims却将prose填null。
有可辨认事实时写出prose；仅确无任何可辨认事实时才用prose=null且claims=[]。
不要把上轮“未生成文案”误读成原文没有事实；反馈只说明上一版输出问题，不替代原文判断。'''
    pipeline.previous.VERSION = VERSION
    pipeline.previous.IMPLEMENTATION_FILES = list(dict.fromkeys(
        pipeline.previous.IMPLEMENTATION_FILES + ['delivery_v62.py']))


if __name__ == '__main__':
    activate()
    current.current.integrated.previous.main()
