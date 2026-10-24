import unittest
import asr_scope_fidelity as precision


class AsrStatePrecision(unittest.TestCase):
    def test_placement_not_installed(self):
        self.assertTrue(precision.issues('窗户放好了，厨房窗户较大。','厨房窗户已安装，尺寸较大。'))

    def test_explicit_installation_not_rejected(self):
        self.assertFalse(precision.issues('窗户安装完成，厨房窗户较大。','厨房窗户较大，已安装完成。'))

    def test_furniture_progress_not_whole_house(self):
        self.assertTrue(precision.issues('桌子要做新样式，但是装了一半。','住宅装修进度为半完成状态。'))

    def test_explicit_whole_progress_kept(self):
        self.assertFalse(precision.issues('桌子装了一半。住宅装修装了一半。','住宅装修进度为半完成状态。'))

    def test_clear_window_size_not_replaced_by_unstated_state(self):
        self.assertTrue(precision.issues('厨房的窗户很大。','厨房窗户采用环保材料。'))
        self.assertFalse(precision.issues('厨房的窗户很大。','厨房配置较大窗户。'))


if __name__=='__main__':unittest.main()
