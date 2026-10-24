import unittest
from prose_claim_evidence_review import verify, payload


class ProseReviewTests(unittest.TestCase):
    def decision(self, status='supported', ids=None):
        return {'fragment_id': 1, 'status': status, 'source_evidence_ids': [1] if ids is None else ids,
            'why': '当前事实逐字支持', 'confidence': .95}

    def response(self, decision):
        return {'checks': [decision], 'coverage': {'captures_primary_points': True,
            'source_evidence_ids': [1], 'why': '已保留主要事实', 'confidence': .95}}

    def test_supported_source_grounded_prose(self):
        okay, audit = verify('距地铁750米。', '地铁站距离750米。', self.response(self.decision()))
        self.assertTrue(okay)
        self.assertIn('750米', audit[0]['verified_source_quote'])

    def test_bad_distance_object_reviewer_rejects(self):
        decision = self.decision('unsupported')
        decision['why'] = '750米只对应地铁站，不对应西四环'
        okay, audit = verify('西四环一河之隔，距地铁750米。', '距西四环及地铁750米。', self.response(decision))
        self.assertFalse(okay)
        self.assertFalse(audit[0]['accepted'])

    def test_invented_material_reviewer_rejects(self):
        okay, _ = verify('竹竹桃楠的竹竹', '采用竹桃楠环保材料', self.response(self.decision('uncertain')))
        self.assertFalse(okay)

    def test_missing_or_duplicate_prose_fragments_fail(self):
        for checks in ([], [self.decision(), self.decision()]):
            okay, _ = verify('源事实', '一条文案', {'checks': checks})
            self.assertFalse(okay)

    def test_unknown_source_evidence_fails(self):
        okay, _ = verify('源事实', '一条文案', self.response(self.decision(ids=[999])))
        self.assertFalse(okay)

    def test_low_confidence_fails(self):
        decision = self.decision()
        decision['confidence'] = .89
        self.assertFalse(verify('源事实', '一条文案', self.response(decision))[0])

    def test_identity_is_not_added_to_source_fact_catalogue(self):
        request = payload('距地铁750米', '出行便捷', '甲项目有泳池')
        self.assertNotIn('泳池', str(request['source_evidence_catalog']))

    def test_missing_primary_coverage_does_not_pass(self):
        self.assertFalse(verify('完整原文', '生成文案', {'checks': [self.decision()]})[0])

    def test_only_affirmation_omits_the_primary_fact(self):
        response = self.response(self.decision())
        response['coverage']['captures_primary_points'] = False
        response['coverage']['why'] = '遗漏喷气发动机吹雪这个核心事实'
        self.assertFalse(verify('下雪用喷气发动机吹雪，这是附近人的经验',
            '这是周围人才能给出的经验', response)[0])


if __name__ == '__main__':unittest.main()
