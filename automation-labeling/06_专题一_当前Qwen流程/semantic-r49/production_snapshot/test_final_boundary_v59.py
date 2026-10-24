import unittest
from unittest.mock import patch
import final_boundary_v59 as v
import delivery_v59 as pipeline


class FinalBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.doc = {'kind': '文章', 'text': '完整户型前半段，接着介绍阳台。会所设有泳池。'}
        self.plan = {'units': [{'source_start_id': 1, 'source_end_id': 1}]}
        self.segments = [{'id': 1, 'start': 0, 'end': len(self.doc['text']), 'text': self.doc['text']}]

    def test_comment_never_boundary_split(self):
        with self.assertRaises(ValueError):
            v.review(dict(self.doc, kind='评论'), self.plan, self.segments, object(), object())

    def test_protocol_failure_keeps_original_partition_and_marks_error(self):
        with patch.object(v, 'bounded', return_value=(None, [], [], ['API失败'])):
            out, segments, audit, calls, errors = v.review(self.doc, self.plan, self.segments,
                                                         object(), pipeline._quote_partition)
        self.assertEqual(out, self.plan)
        self.assertEqual(segments, self.segments)
        self.assertTrue(errors)

    def test_lossless_new_boundaries_keep_complete_floorplan(self):
        raw = {'units': [
            {'start_quote': '完整户型前半段，接着介绍阳台。', 'start_occurrence': 1,
             'object': '同一户型', 'theme': '配置', 'why': '对象未转换', 'confidence': .95, 'uncertainties': []},
            {'start_quote': '会所设有泳池。', 'start_occurrence': 1,
             'object': '会所', 'theme': '设施', 'why': '新物理对象', 'confidence': .94, 'uncertainties': []}]}
        with patch.object(v, 'bounded', return_value=(raw, [], [], [])):
            out, segments, audit, calls, errors = v.review(self.doc, self.plan, self.segments,
                                                         object(), pipeline._quote_partition)
        self.assertEqual(errors, [])
        self.assertEqual(''.join(s['text'] for s in segments), self.doc['text'])
        self.assertEqual(len(out['units']), 2)
        self.assertIn('阳台', segments[0]['text'])
        self.assertNotIn('会所', segments[0]['text'])

    def test_invalid_start_never_reconstructs_or_drops_source(self):
        raw = {'units': [{'start_quote': '模型编造起点', 'start_occurrence': 1,
                         'object': '对象', 'theme': '主题', 'why': '说明', 'confidence': .95, 'uncertainties': []}]}
        with patch.object(v, 'bounded', return_value=(raw, [], [], [])):
            out, segments, audit, calls, errors = v.review(self.doc, self.plan, self.segments,
                                                         object(), pipeline._quote_partition)
        self.assertTrue(errors)
        self.assertEqual(out, self.plan)
        self.assertEqual(segments, self.segments)


if __name__ == '__main__':
    unittest.main()
