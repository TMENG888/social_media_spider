import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parents[1]/'src'))
from keyword_coverage import assess_coverage

class KeywordCoverageTests(unittest.TestCase):
    @staticmethod
    def checkpoint(key=None, url=None, status='completed', project='test'):
        return {'status': status, 'project': project, 'article_key': key,
                'row': {'url': url}}

    def test_duplicate_successful_cards_cannot_inflate_80_percent(self):
        checkpoints={str(i): self.checkpoint('same-video') for i in range(8)}
        checkpoints.update({'missing-1': self.checkpoint('other-1', status='retry_pending'),
                            'missing-2': self.checkpoint('other-2', status='skipped_unresolved')})
        result=assess_coverage(checkpoints, list(checkpoints), scan_complete=True)
        self.assertFalse(result['ok'])
        self.assertEqual((result['numerator'], result['denominator']), (1, 3))
        self.assertEqual(result['discoveredCheckpointCount'], 10)
        self.assertEqual(result['duplicateCheckpointCount'], 7)

    def test_canonical_share_aliases_count_once(self):
        url='https://weixin.qq.com/sph/AbCd1234'
        checkpoints={'old': self.checkpoint('old-key', url+'?tracking=old'),
                     'new': self.checkpoint('new-key', url+'?tracking=new', status='retry_pending')}
        result=assess_coverage(checkpoints, ['old'], scan_complete=True)
        self.assertEqual((result['numerator'], result['denominator']), (1, 1))
        # An older checkpoint may have lost the URL but retained its exact DB key.
        checkpoints['without-url']=self.checkpoint('new-key', status='retry_pending')
        self.assertEqual(assess_coverage(checkpoints, ['old'], scan_complete=True)['denominator'], 1)

    def test_conflicting_share_urls_do_not_merge_on_article_key(self):
        checkpoints={'a': self.checkpoint('same-key', 'https://weixin.qq.com/sph/AbCd1234'),
                     'b': self.checkpoint('same-key', 'https://weixin.qq.com/sph/EfGh5678', status='retry_pending'),
                     'unknown': self.checkpoint('same-key', status='retry_pending')}
        result=assess_coverage(checkpoints, ['a'], scan_complete=True)
        self.assertEqual((result['numerator'], result['denominator']), (1, 3))
        self.assertFalse(result['ok'])

    def test_unknown_identity_and_distinct_projects_stay_separate(self):
        checkpoints={'a': self.checkpoint('same-key', project='first'),
                     'b': self.checkpoint('same-key', project='second'),
                     'unknown-1': self.checkpoint(), 'unknown-2': self.checkpoint(),
                     'no-project-1': self.checkpoint('same-key', project=None),
                     'no-project-2': self.checkpoint('same-key', project=None)}
        for cp in checkpoints.values():
            cp['row']['title']='same title'
        self.assertEqual(assess_coverage(checkpoints, [], scan_complete=True)['denominator'], 6)

    def test_80_percent_with_skips_retained(self):
        checkpoints={str(i):{'status':'completed' if i<8 else 'skipped_unresolved'} for i in range(10)}
        result=assess_coverage(checkpoints,[str(i) for i in range(10)],scan_complete=True)
        self.assertTrue(result['ok']);self.assertEqual(result['numerator'],8)
        self.assertEqual(result['denominator'],10)
        self.assertFalse(assess_coverage(checkpoints,[str(i) for i in range(7)],scan_complete=True)['ok'])
    def test_scan_and_database_evidence_both_required(self):
        self.assertFalse(assess_coverage({'a':{'status':'completed'}},['a'])['ok'])
        self.assertFalse(assess_coverage({'a':{'status':'completed'}},[],scan_complete=True)['ok'])
        self.assertFalse(assess_coverage({'a':{'status':'invalid_json'}},['a'],scan_complete=True)['ok'])
