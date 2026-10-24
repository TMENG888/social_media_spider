"""Offline contracts only: no model downloads, API calls or source data."""
import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'04_专题二_观点信息单元'))
import slice_sentiment_v107 as s
import topic2_heat_v110 as heat

def fixture(text='好看',probability=0.75):
    identity={'test':'fixture-not-a-model'}
    stage={'version':s.VERSION,'model_identity':identity,'signature':s.signature(text,identity),
           'messages':[{'role':'parent','text':text,'token_count':1,'positive_probability':probability,
                        'segments':[{'start_token':0,'end_token':1,'positive_probability':probability}]}],
           'response':{'score':round(100*probability,2),'positive_probability':probability,
                       'evidence':[{'quote':text,'role':'parent'}]}}
    return stage,identity

class LocalSentimentContract(unittest.TestCase):
    def test_nicknames_are_not_model_input(self):
        self.assertEqual(s.parsed_messages('【父评论｜甲】方便【子评论1｜乙】不好停车'),[('parent','方便'),('reply','不好停车')])

    def test_long_input_uses_three_bounded_spans(self):
        spans=s.spans(1600)
        self.assertEqual(len(spans),3)
        self.assertTrue(all(0<b-a<=510 for a,b in spans))
        self.assertEqual(spans[0][0],0)
        self.assertEqual(spans[-1][1],1600)

    def test_formula_and_input_provenance(self):
        stage,identity=fixture()
        self.assertEqual(s._validate(stage,'好看',identity)['score'],75)

    def test_wrong_source_and_old_cache_are_rejected(self):
        stage,identity=fixture()
        for changed in ['别的切片','父文章']:
            with self.assertRaises(ValueError):s._validate(stage,changed,identity)

    def test_invented_evidence_and_wrong_score_are_rejected(self):
        stage,identity=fixture()
        for key,value in [('score',99),('evidence',[{'quote':'父文的事实','role':'parent'}])]:
            changed=copy.deepcopy(stage);changed['response'][key]=value
            with self.assertRaises(ValueError):s._validate(changed,'好看',identity)

    def test_nonfinite_and_boolean_probabilities_are_rejected(self):
        for p in [True,float('nan'),float('inf'),-0.1,1.1]:
            stage,identity=fixture();stage['messages'][0]['segments'][0]['positive_probability']=p
            with self.assertRaises(ValueError):s._validate(stage,'好看',identity)

    def test_heat_missing_is_not_zero(self):
        self.assertIsNone(heat.existing_heat(''))
        self.assertEqual(heat.existing_heat(0),0)
        with self.assertRaises(ValueError):heat.existing_heat(True)

if __name__=='__main__':unittest.main()
