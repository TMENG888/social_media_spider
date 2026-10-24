import copy
import unittest
import identity_relation_index_v97 as m


class RelationIndexTests(unittest.TestCase):
    def setUp(self):
        self.contexts = {'title': '长沙江山境', 'source': '招商蛇口开发长沙江山境。'}
        self.business = {'entities': [{'entity': '招商蛇口', 'brand': '招商'}]}
        self.job = {'record_id': 'A', 'job_id': 'A-0', 'contexts': self.contexts}
        self.check = dict(approve=True, same_object=True, all_objects_covered=True,
                          residential_identity=True, no_identity_conflict=True)
        self.resolved = {'decisions': [{'field': '经营主体', 'unit_id': 'U', 'values': ['招商蛇口'],
              'review': self.check, 'evidence': m.spans(self.contexts, '招商蛇口')}],
              'audit': [{'raw_response': {'objects': [{'unit_id': 'U', 'project_names': ['江山境'],
                          'confidence': .95}]}, 'protocol_issues': []}]}
        self.candidate = m.candidate_relations(self.job, self.resolved, self.business)[0]
        self.review = {'relation_id': self.candidate['relation_id'], 'approve': True,
              'same_project': True, 'joint_or_conflicting_entity': False, 'relation_type': 'development',
              'confidence': .95, 'why': '原文明确开发关系', 'city': '长沙',
              'city_evidence': m.spans(self.contexts, '长沙'),
              'relation_evidence': [{'source': 'source', 'start': 0, 'end': len(self.contexts['source']), 'text': self.contexts['source']}]}

    def test_candidate_is_not_verified(self):
        self.assertFalse(m.relation_leads('江山境', 'A', '长沙', [self.candidate])['leads'])

    def test_existing_workbook_values_not_evidence(self):
        self.assertEqual(m.candidate_relations(self.job, {'decisions': [], 'audit': self.resolved['audit']}, self.business), [])

    def test_rejected_entity_not_candidate(self):
        r = copy.deepcopy(self.resolved); r['decisions'][0]['review']['approve'] = False
        self.assertEqual(m.candidate_relations(self.job, r, self.business), [])

    def test_missing_scope_not_candidate(self):
        r = copy.deepcopy(self.resolved); r['audit'] = []
        self.assertEqual(m.candidate_relations(self.job, r, self.business), [])

    def test_bad_entity_span_not_candidate(self):
        r = copy.deepcopy(self.resolved); r['decisions'][0]['evidence'][0]['start'] = 100
        self.assertEqual(m.candidate_relations(self.job, r, self.business), [])

    def test_source_hash_binding(self):
        contexts = dict(self.contexts, title='修改后的标题')
        self.assertIn('source_hash_changed', m.verify_relation(self.candidate, self.review, contexts, self.business))

    def test_no_relation_review_no_publication(self):
        r = dict(self.review, approve=False)
        with self.assertRaises(ValueError): m.publish(self.candidate, r, self.contexts, self.business)

    def test_property_supplier_not_ownership(self):
        r = dict(self.review, relation_type='property_management')
        self.assertIn('not_development_or_operation', m.verify_relation(self.candidate, r, self.contexts, self.business))

    def test_joint_entities_not_uniquely_mapped(self):
        r = dict(self.review, joint_or_conflicting_entity=True)
        self.assertIn('joint_or_conflicting_entity', m.verify_relation(self.candidate, r, self.contexts, self.business))

    def test_missing_literal_name_fails(self):
        r = dict(self.review, relation_evidence=m.spans(self.contexts, '招商蛇口'))
        self.assertIn('relation_evidence_has_no_literal_project_name', m.verify_relation(self.candidate, r, self.contexts, self.business))

    def test_source_local_without_city(self):
        e = m.publish(self.candidate, dict(self.review, city=None, city_evidence=[]), self.contexts, self.business)
        self.assertTrue(m.relation_leads('江山境', 'A', None, [e])['leads'])
        self.assertFalse(m.relation_leads('江山境', 'B', None, [e])['leads'])

    def test_cross_city_refused(self):
        e = m.publish(self.candidate, self.review, self.contexts, self.business)
        self.assertFalse(m.relation_leads('江山境', 'B', '西安', [e])['leads'])
        self.assertTrue(m.relation_leads('江山境', 'B', '长沙', [e])['leads'])

    def test_not_substring_or_phonetic(self):
        e = m.publish(self.candidate, self.review, self.contexts, self.business)
        self.assertFalse(m.relation_leads('江山', 'A', '长沙', [e])['leads'])
        self.assertFalse(m.relation_leads('江杉境', 'A', '长沙', [e])['leads'])

    def test_typography_only_normalization(self):
        self.assertEqual(m.name_key('招商·江山境'), m.name_key('招商 江山境'))
        self.assertNotEqual(m.name_key('招商江山境'), m.name_key('江山境'))

    def test_conflicts_not_majority_vote(self):
        e = m.publish(self.candidate, self.review, self.contexts, self.business)
        other = dict(e, entity='招商建管')
        result = m.relation_leads('江山境', 'B', '长沙', [e, e, other])
        self.assertEqual(result['stop_reason'], 'conflicting_verified_project_entities')
        self.assertEqual(result['leads'], [])

    def test_input_unchanged(self):
        frozen = copy.deepcopy((self.job, self.resolved, self.business))
        m.candidate_relations(self.job, self.resolved, self.business)
        self.assertEqual((self.job, self.resolved, self.business), frozen)


if __name__ == '__main__': unittest.main()
