import unittest
from marketing_evidence_scope import factual_scope
from multilabel_v2 import MARKETING


class MixedInvitationEvidence(unittest.TestCase):
    def test_unpunctuated_positive_fact_kept(self):
        source='双阳台+LDKG一体化设计总价400-500万级兴趣伙伴可扫码对接销售咨询'
        scoped=factual_scope(source,MARKETING)
        self.assertIn('双阳台+LDKG一体化设计',scoped)
        self.assertNotIn('扫码',scoped)
        self.assertIn('扫码',source)

    def test_fact_after_invitation_phrase_not_erased(self):
        source='预约看房，住宅厨房安装专用烟道止逆阀'
        self.assertIn('厨房安装专用烟道止逆阀',factual_scope(source,MARKETING))

    def test_invitation_only_gives_no_evidence(self):
        self.assertEqual('',factual_scope('私信预约看房',MARKETING))


if __name__=='__main__':unittest.main()
