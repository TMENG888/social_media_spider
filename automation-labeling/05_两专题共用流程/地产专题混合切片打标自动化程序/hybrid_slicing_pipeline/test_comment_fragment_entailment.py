import copy
import unittest
import comment_fragment_entailment as review


class Runner:
    def __init__(self):self.payloads=[]
    def call(self,system,payload,doc,phase):
        self.payloads.append(payload);fragment=payload['prose_catalog'][0]
        key=payload['source_evidence_catalog'][0]['source_key']
        response={'checks':[{'prose_key':fragment['prose_key'],'assertion_quote':fragment['text'],
            'source_keys':[key],'status':'supported','object_binding_supported':True,
            'relation_supported':True,'modality_preserved':True,'qualifiers_preserved':True,
            'why':'当前表述与所选原文一致','confidence':.95,
            'object_bindings':[{'assertion_quote':fragment['text'],'object_quote':None,
                'object_source_key':None,'attribute_source_key':key,
                'attribute_quote':payload['source_evidence_catalog'][0]['text'],
                'generic_or_unresolved':True}]}]}
        if '禁止另造assertion_quote' in system:
            check=response['checks'][0];check.pop('assertion_quote')
            response['object_bindings']=check.pop('object_bindings')
            for binding in response['object_bindings']:
                binding.pop('assertion_quote');binding['prose_key']=fragment['prose_key']
        if '禁止返回attribute_quote或assertion_quote' in system:
            check=response['checks'][0];check.pop('assertion_quote')
            response['object_bindings']=check.pop('object_bindings')
            for binding in response['object_bindings']:
                binding.pop('assertion_quote');binding.pop('attribute_quote')
                binding.pop('generic_or_unresolved')
                binding['prose_key']=fragment['prose_key']
        return response,{'status':'success'}


class FragmentReviewTests(unittest.TestCase):
    def test_one_actual_fragment_per_request_but_complete_original_is_preserved(self):
        source='【父评论｜甲】道路很堵，假期稍好。【子评论1｜乙】我觉得轮渡慢。'
        runner=Runner();okay,audit,calls=review.review(source,'交通堵，仅假期稍好。乙认为轮渡慢。',{},runner)
        self.assertTrue(okay);self.assertEqual(2,len(calls))
        self.assertTrue(all(p['source_text']==source and len(p['prose_catalog'])==1 for p in runner.payloads))
        self.assertTrue(all('coverage' not in a for a in audit))

    def test_fabricated_assertion_unknown_reference_and_wrong_key_are_rejected(self):
        runner=Runner();review.review('道路很堵。','交通堵。',{},runner)
        payload=runner.payloads[0];response,_=runner.call('',payload,{},'')
        fragment=payload['prose_catalog'][0];sources=payload['source_evidence_catalog']
        for field,value in [('assertion_quote','噪音导致堵车'),('prose_key','wrong'),('source_keys',['unknown'])]:
            candidate=copy.deepcopy(response);candidate['checks'][0][field]=value
            self.assertFalse(review.verify_one(fragment,sources,candidate)[0])

    def test_negative_semantics_not_overridden_by_confidence(self):
        runner=Runner();review.review('道路很堵。','交通堵。',{},runner)
        p=runner.payloads[0];response,_=runner.call('',p,{},'')
        response['checks'][0].update(status='uncertain',confidence=.99)
        self.assertFalse(review.verify_one(p['prose_catalog'][0],p['source_evidence_catalog'],response)[0])

    def test_root_level_bindings_have_one_unambiguous_fragment_owner(self):
        runner=Runner();review.review('道路很堵。','交通堵。',{},runner)
        p=runner.payloads[0];response,_=runner.call('',p,{},'')
        response['object_bindings']=response['checks'][0].pop('object_bindings')
        self.assertTrue(review.verify_one(p['prose_catalog'][0],p['source_evidence_catalog'],response)[0])


if __name__=='__main__':unittest.main()
