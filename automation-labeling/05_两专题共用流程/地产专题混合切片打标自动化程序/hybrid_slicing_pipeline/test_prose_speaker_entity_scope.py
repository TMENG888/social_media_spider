import unittest
from prose_speaker_entity_scope import issues


class SpeakerEntityTests(unittest.TestCase):
    source='【父评论｜玺宝宝】保利熙瑞价格高。【子评论1｜嘉棠】我纠结太平桥，爱人嫌弃太平桥南。'
    def test_observed_nickname_property_list_confusion_is_flagged(self):
        self.assertTrue(issues(self.source,'保利熙瑞、嘉棠等房源因价格或位置引发纠结。'))
    def test_correct_actor_attribution_is_not_rejected(self):
        self.assertFalse(issues(self.source,'嘉棠称自己纠结太平桥，爱人不喜欢太平桥南。'))
        self.assertFalse(issues(self.source,'评论者对保利熙瑞价格和太平桥位置表达疑虑。'))
    def test_real_project_coinciding_with_nickname_is_not_automatically_vetoed(self):
        source='【父评论｜安澜】安澜项目的位置好。'
        self.assertFalse(issues(source,'安澜项目位置较好。'))
    def test_articles_without_comment_headers_are_not_changed(self):
        self.assertFalse(issues('甲项目规划公园。','甲项目规划公园。'))


if __name__=='__main__':unittest.main()
