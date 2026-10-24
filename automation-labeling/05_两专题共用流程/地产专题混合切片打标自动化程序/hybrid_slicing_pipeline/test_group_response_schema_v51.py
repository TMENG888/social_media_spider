import copy
import json
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch
import delivery_v4 as base
import group_response_schema_v51 as contract
import source_only_group_recovery_v50 as protocol


class SchemaEvidenceOwnership(unittest.TestCase):
    def setUp(self):
        self.entries=[{'source_unit_key':'A','text':'卫生间防臭方案。'},
                      {'source_unit_key':'B','text':'存水弯配自动补水。'}]

    def test_required_confidence_and_exact_member_keys(self):
        schema=contract.schema(self.entries,self.entries)
        self.assertIn('confidence',schema['required'])
        self.assertEqual(['A','B'],schema['properties']['member_roles']['required'])
        self.assertFalse(schema['additionalProperties'])
        self.assertNotIn('object_quote',schema['properties']['object_references']['items']['properties'])

    def test_program_owns_literal_source_and_preserves_raw_response(self):
        raw={'object_references':[{'source_unit_key':'A'}]};original=copy.deepcopy(raw)
        resolved,issues=contract.materialize(raw,self.entries)
        self.assertFalse(issues);self.assertEqual(original,raw)
        self.assertEqual('卫生间防臭方案。',resolved['object_references'][0]['object_quote'])

    def test_legacy_quote_unknown_key_and_duplicate_rejected(self):
        for refs in ([{'source_unit_key':'A','object_quote':'卫生间'}],
                     [{'source_unit_key':'X'}],[{'source_unit_key':'A'},{'source_unit_key':'A'}]):
            self.assertTrue(contract.materialize({'object_references':refs},self.entries)[1])

    def test_strict_live_protocol_materializes_only_new_key_schema(self):
        raw={'approved':True,'kind':'same_object','confidence':.95,'object_references':[{'source_unit_key':'A'}]}
        class Runner:
            supports_response_schema=True
            def __init__(self):self.schemas=[]
            def call(self,system,payload,doc,phase,**kwargs):
                self.schemas.append(kwargs['response_schema']);return raw,{'status':'success'}
        runner=Runner()
        out,audit,calls,issues=protocol.review({'text':'卫生间防臭方案。存水弯配自动补水。','topic':'全国地产设计产品力监测'},
            self.entries,0,1,runner,'S',lambda r:[])
        self.assertFalse(issues);self.assertEqual(1,len(runner.schemas))
        self.assertEqual(raw,audit[0]['response']);self.assertNotIn('object_quote',raw['object_references'][0])
        self.assertEqual(self.entries[0]['text'],out['object_references'][0]['object_quote'])

    def test_transport_and_cache_key_include_response_schema(self):
        requests=[]
        def fake_post(url,body,key,timeout):
            requests.append(copy.deepcopy(body))
            return SimpleNamespace(status_code=200,json=lambda:{'choices':[{'finish_reason':'stop','message':{'content':json.dumps({'confidence':.95})}}],
                'usage':{'prompt_tokens':10,'completion_tokens':5,'total_tokens':15}})
        doc={'record_id':'TEST','topic':'T1','kind':'文章'}
        with tempfile.TemporaryDirectory() as folder,patch.object(base,'post_json',fake_post):
            runner=base.ApiRunner(folder,10,key='test-only-placeholder')
            _,plain=runner.call('S',{'text':'x'},doc,'test')
            _,strict=runner.call('S',{'text':'x'},doc,'test',response_schema=contract.schema(self.entries,self.entries))
            self.assertNotEqual(plain['request_key'],strict['request_key'])
            self.assertEqual('json_object',requests[0]['response_format']['type'])
            self.assertEqual('json_schema',requests[1]['response_format']['type'])
            self.assertTrue(requests[1]['response_format']['json_schema']['strict'])
            _,cached=runner.call('S',{'text':'x'},doc,'test',response_schema=contract.schema(self.entries,self.entries))
            self.assertTrue(cached['cache_hit']);self.assertEqual(2,len(requests))


if __name__=='__main__':unittest.main()
