import unittest
from prose_speaker_catalog import source_catalog
from label_evidence_reference import evidence_catalog, resolve_evidence_ids


class SpeakerCatalogueTests(unittest.TestCase):
    def test_continuation_belongs_to_actual_child_speaker(self):
        source = ('【父评论｜教练】价格贵。'
                  '【子评论1｜玺宝宝】西冉地块北是瘸子里拔将军！'
                  '海淀北朱房双子也是临快速路，其中一个还是夹角。'
                  '只有安澜位置好。'
                  '【子评论2｜嘉棠】我纠结太平桥，爱人嫌弃太平桥南。')
        entries = source_catalog(source)
        for entry in entries:
            if '朱房双子' in entry['text'] or '只有安澜' in entry['text']:
                self.assertEqual('玺宝宝', entry['speaker'])
            if '我纠结太平桥' in entry['text']:
                self.assertEqual('嘉棠', entry['speaker'])
        self.assertEqual([(e['evidence_id'],e['text']) for e in evidence_catalog(source)],
                         [(e['evidence_id'],e['text']) for e in entries])
        for entry in entries:
            self.assertEqual(entry['text'],resolve_evidence_ids([entry['evidence_id']],entries))

    def test_nickname_is_not_a_professional_role(self):
        entries=source_catalog('【子评论1｜北京安信房产置业丨盛丰】您好，项目规划在永引渠上架一座桥。')
        self.assertEqual('北京安信房产置业丨盛丰',entries[0]['speaker'])
        self.assertNotIn('role',entries[0])

    def test_article_does_not_invent_speaker(self):
        self.assertTrue(all(e['speaker'] is None for e in source_catalog('住宅设南向阳台。层高3.4米。')))


if __name__ == '__main__': unittest.main()
