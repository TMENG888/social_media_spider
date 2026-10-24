import unittest
import bounded_visible_contract_v60 as v


class VisibleContractTests(unittest.TestCase):
    def setUp(self):
        self.schema = {'type': 'object', 'properties': {
            'why': {'type': 'string', 'minLength': 1},
            'source_keys': {'type': 'array', 'items': {'type': 'string'}}},
            'required': ['why', 'source_keys'], 'additionalProperties': False}
        self.payload = {'source_catalog': [{'source_key': 'SRC-actual'}]}

    def test_input_schema_not_mutated(self):
        actual = v.contract(self.schema, self.payload)
        self.assertNotIn('maxLength', self.schema['properties']['why'])
        self.assertEqual(actual['properties']['why']['maxLength'], 160)

    def test_only_literal_catalog_keys(self):
        actual = v.contract(self.schema, self.payload)
        self.assertEqual(actual['properties']['source_keys']['items']['enum'], ['SRC-actual'])

    def test_parent_comment_namespaces_not_combined(self):
        schema = {'type': 'object', 'properties': {k: {'type': 'array', 'items': {'type': 'string'}}
                  for k in ('comment_keys', 'parent_identity_keys')}}
        payload = {'comment_catalog': [{'source_key': 'COMMENT-A'}],
                   'parent_catalog': [{'source_key': 'PARENT-B'}]}
        actual = v.contract(schema, payload)['properties']
        self.assertEqual(actual['comment_keys']['items']['enum'], ['COMMENT-A'])
        self.assertEqual(actual['parent_identity_keys']['items']['enum'], ['PARENT-B'])

    def test_model_receives_contract_not_only_gateway(self):
        calls = []
        class Runner:
            def call(self, system, payload, doc, phase, **kwargs):
                calls.append((system, payload, kwargs))
                return {'why': '原文支持', 'source_keys': ['SRC-actual']}, {'status': 'success'}
        raw, metrics, audit, errors = v.review('核查', self.payload, self.schema, {}, 'phase', Runner())
        self.assertEqual(errors, [])
        self.assertIn('output_contract', calls[0][1])
        self.assertEqual(calls[0][1]['output_contract'], calls[0][2]['response_schema'])

    def test_valid_negative_no_semantic_pressure_retry(self):
        count = []
        class Runner:
            def call(self, *args, **kwargs):
                count.append(1)
                return {'why': '未提供对象证据', 'source_keys': []}, {'status': 'success'}
        raw, metrics, audit, errors = v.review('核查', self.payload, self.schema, {}, 'phase', Runner())
        self.assertEqual(errors, [])
        self.assertEqual(len(count), 1)


if __name__ == '__main__':
    unittest.main()
