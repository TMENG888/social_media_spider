import unittest
import delivery_v62 as v
import comment_identity_protocol_v59 as identity
from structured_response_validation_v58 import issues


class ContractTests(unittest.TestCase):
    def test_comment_and_parent_namespaces_are_disjoint(self):
        payload = identity.payload('评论甲', '父文乙', [])
        schema = v.contract(identity.SCHEMA, payload)
        fields = schema['properties']['targets']['items']['properties']
        comment = fields['comment_keys']['items']['enum']
        parent = fields['parent_identity_keys']['items']['enum']
        self.assertTrue(all(x.startswith('COMMENT-') for x in comment))
        self.assertTrue(all(x.startswith('PARENT-') for x in parent))
        self.assertFalse(set(comment) & set(parent))
        self.assertNotIn('enum', identity.KEYS['items'])

    def test_null_prose_with_claims_is_not_valid(self):
        response = {'prose': None, 'claims': [{'text': '配置明确', 'source_keys': ['SRC-A']}],
                    'confidence': 1, 'why': '有明确事实'}
        self.assertTrue(issues(response, v.generation_schema()))
        response['prose'] = '采用明确配置。'
        self.assertFalse(issues(response, v.generation_schema()))

    def test_genuine_no_fact_can_remain_null_and_uncertain(self):
        response = {'prose': None, 'claims': [], 'confidence': .2, 'why': '无法辨认'}
        self.assertFalse(issues(response, v.generation_schema()))


if __name__ == '__main__':
    unittest.main()
