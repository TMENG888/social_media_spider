import copy
import unittest
from unittest.mock import patch
import identity_relation_review_v97 as m
import identity_relation_index_v97 as index
from identity_completion_v97 import catalog


class RelationReviewTests(unittest.TestCase):
    def setUp(self):
        self.contexts = {'title': '长沙江山境', 'source': '招商蛇口开发长沙江山境。'}
        self.business = {'entities': [{'entity': '招商蛇口', 'brand': '招商'}]}
        self.c = {'relation_id': 'R', 'record_id': 'A', 'unit_id': 'U', 'project_name': '江山境',
                  'entity': '招商蛇口', 'brand': '招商', 'context_hash': index.digest(self.contexts),
                  'entity_evidence': index.spans(self.contexts, '招商蛇口')}
        keys = [e['source_key'] for e in catalog(self.contexts)]
        self.yes = {'relation_id': 'R', 'decision': 'verified_relation', 'relation_type': 'development',
                'same_project': True, 'joint_or_conflicting_entity': False, 'city': '长沙',
                'source_keys': [keys[1]], 'city_source_keys': [keys[0]], 'why': '原文明确开发关系', 'confidence': .95}
        self.no = dict(self.yes, decision='no_supported_relation', relation_type='none', source_keys=[],
                       city=None, city_source_keys=[], why='全文未证实此开发关系')

    def resolve(self, one, two):
        with patch.object(m, 'review', side_effect=[(copy.deepcopy(one), [], [], []), (copy.deepcopy(two), [], [], [])]):
            return m.resolve(self.c, self.contexts, self.business, None, {'record_id': 'A'})

    def test_two_positive_relations_publish(self):
        self.assertEqual(self.resolve(self.yes, self.yes)['state'], 'verified')

    def test_reviewer_disagrees_no_publication(self):
        result = self.resolve(self.yes, self.no)
        self.assertEqual(result['state'], 'review_disagreement'); self.assertNotIn('entry', result)

    def test_two_negative_decisions_not_failure(self):
        self.assertEqual(self.resolve(self.no, self.no)['state'], 'confirmed_no_supported_relation')

    def test_city_difference_not_silently_inherited(self):
        two = dict(self.yes, city=None, city_source_keys=[])
        self.assertEqual(self.resolve(self.yes, two)['state'], 'review_disagreement')

    def test_fake_key_rejected(self):
        one = dict(self.yes, source_keys=['Evidence-1'])
        self.assertEqual(self.resolve(one, self.yes)['state'], 'review_disagreement')

    def test_wrong_relation_target_rejected(self):
        self.assertEqual(self.resolve(dict(self.yes, relation_id='OTHER'), self.yes)['state'], 'review_disagreement')

    def test_negative_claims_development_is_contradiction(self):
        bad = dict(self.no, relation_type='development')
        self.assertEqual(self.resolve(bad, bad)['state'], 'review_disagreement')

    def test_technical_failure_not_certified_empty(self):
        with patch.object(m, 'review', return_value=(None, [], [], ['API failure'])):
            self.assertEqual(m.resolve(self.c, self.contexts, self.business, None, {'record_id': 'A'})['state'], 'technical_failure')

    def test_input_is_not_mutated(self):
        frozen = copy.deepcopy((self.c, self.contexts, self.business))
        self.resolve(self.yes, self.yes)
        self.assertEqual((self.c, self.contexts, self.business), frozen)


if __name__ == '__main__': unittest.main()
