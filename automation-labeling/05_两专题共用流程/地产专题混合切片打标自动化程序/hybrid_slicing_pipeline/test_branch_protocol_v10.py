import unittest
import delivery_v7 as p
import delivery_v8 as grounding
from unittest.mock import Mock


class BranchProtocol(unittest.TestCase):
    def test_object_in_unsupported_requires_full_explicit_repair(self):
        raw={'matches':[], 'unsupported_keys':[{'choice_key':'D1'}], 'ambiguous':[]}
        self.assertEqual({'D1','D2'},p.disputed_keys(raw,{'D1':{},'D2':{}}))

    def test_repair_does_not_convert_malformed_object_to_rejection(self):
        raw={'matches':['bad'], 'unsupported_keys':[{'choice_key':'D1'}], 'ambiguous':['bad']}
        decisions={'decisions':[{'choice_key':'D1','status':'ambiguous','why':'需要证据'}]}
        fixed,issues=p.apply_decisions(raw,decisions,{'D1'})
        self.assertEqual([],issues)
        self.assertEqual([],fixed['unsupported_keys'])
        self.assertEqual([],fixed['matches'])
        self.assertEqual([{'choice_key':'D1','reason':'需要证据'}],fixed['ambiguous'])

    def test_valid_partition_keeps_original_conflict_behavior(self):
        raw={'matches':[{'choice_key':'D1'}], 'unsupported_keys':['D1'], 'ambiguous':[]}
        self.assertEqual({'D1','D2'},p.disputed_keys(raw,{'D1':{},'D2':{}}))

    def test_recovery_has_literal_slice_not_only_numeric_pointers(self):
        runner=Mock()
        runner.call.return_value=({'decisions':[{'choice_key':'D1','status':'ambiguous','why':'待核'}]}, {'status':'success'})
        raw={'units':[{'source_start_id':1,'source_end_id':1,'labels':[]}],'decisions':[]}
        doc={'kind':'评论','text':'会所设茶室'}
        grounding.repair_decision_partition(raw,doc,{'D1'},{'D1':{}},
            {'label_catalog':[{'choice_key':'D1'}]},runner)
        payload=runner.call.call_args.args[1]
        self.assertEqual('会所设茶室',payload['current_units'][0]['excerpt'])
        self.assertEqual(0,payload['current_units'][0]['unit_index'])


if __name__=='__main__': unittest.main()
