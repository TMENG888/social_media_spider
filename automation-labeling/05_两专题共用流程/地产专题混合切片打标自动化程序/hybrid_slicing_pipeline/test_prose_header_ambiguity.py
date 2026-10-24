import unittest
from prose_header_ambiguity import issues


class HeadingAmbiguity(unittest.TestCase):
    def test_conjunction_rewrite_does_not_fix_shared_fact_error(self):
        source='甲项目• 乙项目：园林采用现代中式风格。'
        self.assertTrue(issues(source,'甲项目与乙项目采用现代中式风格。'))
    def test_neutral_text_and_explicit_comparison_not_vetoed(self):
        source='甲项目• 乙项目：园林采用现代中式风格。'
        self.assertFalse(issues(source,'该段介绍现代中式园林。'))
        self.assertFalse(issues(source,'对比甲项目与乙项目的园林配置。'))
    def test_clear_joint_subject_is_not_heading_ambiguity(self):
        self.assertFalse(issues('甲项目与乙项目均采用现代中式园林。','甲项目与乙项目采用现代中式园林。'))
    def test_single_project_and_duplicate_heading_not_two_entities(self):
        self.assertFalse(issues('乙项目：现代中式园林。','乙项目采用现代中式园林。'))
        self.assertFalse(issues('乙项目•乙项目：现代中式园林。','乙项目采用现代中式园林。'))


if __name__=='__main__':unittest.main()
