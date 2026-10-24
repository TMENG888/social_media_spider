import unittest
from scope_retention_evidence import supported_retention


class RetentionEvidence(unittest.TestCase):
    def positive(self, kind='product_fact'):
        return {'exclude': False, 'positive_facts': [{'kind': kind,
            'fact': '存水弯水封大于50毫米', 'evidence_ids': [1],
            'why': '明确工法配置', 'confidence': .95}]}

    def test_positive_fact_can_reverse_exclusion(self):
        self.assertTrue(supported_retention(self.positive(), {1}, True))

    def test_generic_real_estate_reason_is_not_product_fact(self):
        self.assertFalse(supported_retention({'exclude': False,
            'why': '提到了工法样板间，与地产有关', 'confidence': .99,
            'evidence_ids': [1]}, {1}, True))

    def test_topic_two_opinion_not_topic_one_configuration(self):
        self.assertFalse(supported_retention(self.positive('opinion'), {1}, True))
        self.assertTrue(supported_retention(self.positive('opinion'), {1}, False))

    def test_marketing_kind_never_admitted(self):
        self.assertFalse(supported_retention(self.positive('marketing_invitation'), {1}, True))

    def test_unknown_reference_or_low_confidence_not_admitted(self):
        self.assertFalse(supported_retention(self.positive(), {2}, True))
        response = self.positive()
        response['positive_facts'][0]['confidence'] = .8
        self.assertFalse(supported_retention(response, {1}, True))

    def test_uncertain_is_not_supported_retention(self):
        response = self.positive()
        response['exclude'] = None
        self.assertFalse(supported_retention(response, {1}, True))

    def test_malformed_model_values_fail_without_crashing(self):
        for field, value in [('evidence_ids', [{}]), ('kind', ['product_fact'])]:
            response = self.positive()
            response['positive_facts'][0][field] = value
            self.assertFalse(supported_retention(response, {1}, True))


if __name__ == '__main__':unittest.main()
