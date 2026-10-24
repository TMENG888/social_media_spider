import unittest
from prose_role_evidence import issues


class RoleEvidence(unittest.TestCase):
    def test_real_reply_account_not_certified_property_advisor(self):
        source='【父评论｜小白薯】750米，你飞过去啊【子评论1｜北京安信房产置业丨盛丰】您好，项目规划在永引渠上架一座桥。'
        self.assertTrue(issues(source,'置业顾问称项目规划在永引渠架桥。'))
        self.assertFalse(issues(source,'回复者称项目规划在永引渠架桥。'))
    def test_role_only_in_nickname_not_body_proof(self):
        self.assertTrue(issues('【子评论1｜置业顾问甲】规划架桥。','置业顾问回复称规划架桥。'))
    def test_explicit_reported_role_not_rejected(self):
        self.assertFalse(issues('销售人员告诉我规划架桥。','置业顾问称规划架桥。'))
    def test_nickname_not_self_media_certification(self):
        self.assertTrue(issues('【父评论｜某某探房】臻澐探盘。','自媒体博主介绍臻澐。'))


if __name__=='__main__':unittest.main()
