import unittest
from prose_source_constraints import issues


class SourceConstraints(unittest.TestCase):
    def test_unseen_video_does_not_prove_audio(self):
        self.assertTrue(issues('再发一个甲地的大飞机[视频]10s', '用户分享飞机噪音视频。'))
        self.assertFalse(issues('再发一个甲地的大飞机[视频]10s', '用户分享甲地大飞机视频。'))

    def test_explicit_audio_is_not_rejected(self):
        self.assertFalse(issues('飞机轰鸣很响[视频]', '用户称飞机声响很大。'))

    def test_parallel_complaints_do_not_prove_cause(self):
        self.assertTrue(issues('临快速路噪音大。还有堵车问题。', '堵车时噪音更大。'))
        self.assertFalse(issues('临快速路噪音大。还有堵车问题。', '用户抱怨噪音大及堵车。'))

    def test_explicit_cause_is_retained(self):
        self.assertFalse(issues('拥堵使得车辆鸣笛噪音更大。', '用户称拥堵使得噪音更大。'))

    def test_relative_unexperienced_choice_is_not_absolute_acceptance(self):
        source='没坐过巴士，如果二选一也许巴士好一点。'
        self.assertTrue(issues(source,'用户认为巴士尚可。'))
        self.assertFalse(issues(source,'用户未坐过，只相对倾向巴士。'))
        self.assertFalse(issues('没坐过巴士，但坐过的轮渡可以接受；相对更倾向轮渡。','用户认为轮渡可以接受。'))


if __name__ == '__main__':
    unittest.main()
