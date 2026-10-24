import copy
import unittest
from continuity_edge_references import catalog,model_catalog,apply,recovery_payload,merge_recovery


class BoundEdgeTests(unittest.TestCase):
    def setUp(self):
        self.excerpts=['甲户型层高3.4米。','该户型做完设备净高超过3米。','附近有小学。']
        self.plan={'units':[{'source_start_id':i+1,'source_end_id':i+1,'relevant':True,
                           'labels':[],'confidence':{}} for i in range(3)]}
        self.entries=catalog(self.excerpts)
        self.response={'edges':[{'edge_key':e['edge_key'],'decision':'same_object' if i==0 else 'keep',
            'theme':'floorplan' if i==0 else None,'objects':'同一户型层高及净高解释' if i==0 else None,
            'why':'层高及净高承接' if i==0 else '户型转教育','confidence':.95} for i,e in enumerate(self.entries)]}
    def test_correct_edge_does_not_depend_on_response_order(self):
        r=copy.deepcopy(self.response);r['edges'].reverse()
        merged,issues=apply(self.plan,r,'北京臻澐项目口碑',self.excerpts)
        self.assertFalse(issues);self.assertEqual(2,len(merged['units']))
        self.assertEqual(2,merged['units'][0]['source_end_id'])
    def test_old_recounted_numeric_keys_are_rejected(self):
        r=copy.deepcopy(self.response)
        for i,e in enumerate(r['edges']):e['edge_key']=f'EDGE-{i:04d}'
        self.assertTrue(apply(self.plan,r,'北京臻澐项目口碑',self.excerpts)[1])
    def test_missing_duplicate_or_different_source_keys_fail(self):
        for edges in (self.response['edges'][:1],self.response['edges'][:1]*2):
            self.assertTrue(apply(self.plan,{'edges':edges},'北京臻澐项目口碑',self.excerpts)[1])
        r=copy.deepcopy(self.response);r['edges'][0]['edge_key']=catalog(['另一户型。','另一个解释。'])[0]['edge_key']
        self.assertTrue(apply(self.plan,r,'北京臻澐项目口碑',self.excerpts)[1])
    def test_model_does_not_receive_positional_unit_indices(self):
        self.assertNotIn('unit_index',str(model_catalog(self.excerpts)))
    def test_actual_text_and_repeated_text_have_distinct_stable_keys(self):
        entries=catalog(['相同。','相同。','相同。'])
        self.assertNotEqual(entries[0]['edge_key'],entries[1]['edge_key'])
        self.assertEqual(entries,catalog(['相同。','相同。','相同。']))
    def test_invalid_semantic_transitive_merge_remains_rejected(self):
        r=copy.deepcopy(self.response);r['edges'][1].update(decision='same_object',theme='education',objects='学校')
        self.assertTrue(apply(self.plan,r,'北京臻澐项目口碑',self.excerpts)[1])
    def test_retry_only_missing_edge_preserves_valid_source_bound_decision(self):
        original={'source_text':''.join(self.excerpts),'topic':'北京臻澐项目口碑',
                  'edge_catalog':model_catalog(self.excerpts)}
        retry,retained,issues=recovery_payload(original,{'edges':self.response['edges'][:1]})
        self.assertEqual(1,len(retry['edge_catalog']))
        self.assertEqual(self.entries[1]['edge_key'],retry['edge_catalog'][0]['edge_key'])
        combined,issues=merge_recovery(original,retained,{'edges':self.response['edges'][1:]})
        self.assertFalse(issues)
        self.assertFalse(apply(self.plan,combined,original['topic'],self.excerpts)[1])
    def test_duplicate_decision_is_recovered_not_arbitrarily_selected(self):
        original={'topic':'北京臻澐项目口碑','edge_catalog':model_catalog(self.excerpts)}
        retry,retained,_=recovery_payload(original,{'edges':self.response['edges'][:1]*2})
        self.assertFalse(retained);self.assertEqual(2,len(retry['edge_catalog']))
    def test_retry_cannot_overwrite_already_valid_edge_or_invent_missing_keep(self):
        original={'topic':'北京臻澐项目口碑','edge_catalog':model_catalog(self.excerpts)}
        _,retained,_=recovery_payload(original,{'edges':self.response['edges'][:1]})
        self.assertIsNone(merge_recovery(original,retained,self.response)[0])
        self.assertIsNone(merge_recovery(original,retained,{'edges':[]})[0])
    def test_complete_but_incoherent_themes_do_not_get_repaired_by_parser(self):
        original={'topic':'北京臻澐项目口碑','edge_catalog':model_catalog(self.excerpts)}
        r=copy.deepcopy(self.response);r['edges'][1].update(decision='same_object',theme='education',objects='学校')
        retry,retained,_=recovery_payload(original,r)
        self.assertEqual(original,retry)
        self.assertTrue(apply(self.plan,r,original['topic'],self.excerpts)[1])


if __name__=='__main__':unittest.main()
