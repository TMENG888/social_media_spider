import unittest
import asr_scope_fidelity as policy


class ASRFidelity(unittest.TestCase):
    def test_furniture_style_not_expanded_to_whole_home(self):
        self.assertTrue(policy.issues('餐桌想做中古风，房子还没装完。','全屋中古风装修。'))

    def test_explicit_whole_home_scope_is_not_blocked(self):
        self.assertFalse(policy.issues('房子全屋采用中古风，餐桌也是中古。','全屋中古风装修。'))

    def test_incomplete_specific_component_not_installed(self):
        self.assertTrue(policy.issues('过滤窗装不完，窗户放好了。','已安装窗户及过滤窗。'))

    def test_unfinished_state_and_other_completed_components_can_coexist(self):
        self.assertFalse(policy.issues('过滤窗装不完，窗户放好了。','窗户已放置，过滤窗尚未完成安装。'))

    def test_noisy_material_is_not_restored_to_specific_material(self):
        self.assertTrue(policy.issues('环保材料，竹竹什么的竹竹。','部分使用竹材等环保材料。'))

    def test_clear_environmental_fact_not_discarded(self):
        self.assertFalse(policy.issues('环保材料，竹竹什么的竹竹。','部分使用环保材料，具体材质不清。'))

    def test_window_size_must_keep_kitchen_object(self):
        self.assertTrue(policy.issues('厨房厨房的窗户也很大，采用环保材料。','窗户已放置且尺寸较大，使用环保材料。'))
        self.assertFalse(policy.issues('厨房厨房的窗户也很大，采用环保材料。','厨房窗户较大，采用环保材料。'))

    def test_furniture_style_cannot_become_general_renovation(self):
        self.assertTrue(policy.issues('这个桌子要装法式，装了一半。','原计划法式装修。'))

    def test_clean_material_name_not_blocked_by_other_noise(self):
        self.assertFalse(policy.issues('竹材柜板，竹竹施工竹竹。','采用竹材柜板。'))

    def test_supported_reason_admitting_guess_needs_review(self):
        self.assertTrue(policy.guessed_asr_reason('疑为语音识别错误，指法式装修。'))
        self.assertFalse(policy.guessed_asr_reason('原文明确采用环保材料。'))


if __name__=='__main__':unittest.main()
