import unittest
from final_issue_resolution import partition


class FinalIssueResolution(unittest.TestCase):
    def test_only_exact_repaired_key(self):
        issues=['支持证据无法逐字定位：D0074','支持证据无法逐字定位：D0076']
        active,resolved=partition(issues,{'D0074'})
        self.assertEqual([issues[1]],active);self.assertEqual([issues[0]],resolved)
    def test_structural_and_semantic_issues_never_hidden(self):
        issues=['分支编号未唯一覆盖全部字典','标签对象或推断待核：D0074','标签证据编号恢复未通过']
        self.assertEqual((issues,[]),partition(issues,{'D0074'}))
    def test_no_prefix_or_fuzzy_match(self):
        issues=['支持证据无法逐字定位：D0074 额外冲突','对象证据无法定位：D00740']
        self.assertEqual((issues,[]),partition(issues,{'D0074'}))


if __name__=='__main__':unittest.main()
