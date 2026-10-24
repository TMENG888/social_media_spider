import unittest
from verify_random_evidence_v10 import inspect


class AnchorEvidence(unittest.TestCase):
    def test_glued_number_is_not_an_expected_label(self):
        doc={'record_id':'T2-8000912876517503108','kind':'文章',
            'topic':'北京臻澐项目口碑','text':'容积率仅1.433-5层纯洋房得房率90%'}
        result={'document':doc,'complete':True,'rows':[]}
        report=inspect([result],[doc],[])
        anchor=next(a for a in report['anchors'] if a['tag_id']=='VOC-0165' and a['record_id']==doc['record_id'])
        self.assertEqual('源证据歧义，保留复核，不计作应打或漏标',anchor['结果'])
        self.assertIn('禁止猜1.43',anchor['源证据限制'])
        clear=next(a for a in report['anchors'] if a['tag_id']=='VOC-0189' and a['record_id']==doc['record_id'])
        self.assertEqual('有据标签未在交付行落地，需定位',clear['结果'])


if __name__=='__main__':unittest.main()
