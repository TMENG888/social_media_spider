import unittest
from label_evidence_reference import evidence_catalog,resolve_evidence_ids

class References(unittest.TestCase):
    def test_comment_source_is_lossless_and_not_output_split(self):
        text='【父评论｜甲】马路噪声很吵【子评论1｜乙】去地铁要绕路。'
        cat=evidence_catalog(text)
        self.assertEqual(text,''.join(s['text'] for s in cat))
        self.assertEqual('【子评论1｜乙】去地铁要绕路。',resolve_evidence_ids([2],cat))
    def test_reordered_ids_canonical_and_illegal_fail(self):
        cat=evidence_catalog('道路噪声。距离200米。')
        self.assertEqual('道路噪声。...距离200米。',resolve_evidence_ids([2,1],cat))
        for ids in ([3],[1,1],['1'],[True],[]):self.assertIsNone(resolve_evidence_ids(ids,cat))

if __name__=='__main__':unittest.main()
