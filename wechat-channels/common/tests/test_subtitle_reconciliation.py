import sys, unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parents[1]/'src'))
from reconcile_subtitle_retries import reason
class ReconciliationTests(unittest.TestCase):
    def test_empty_is_selected(self):
        self.assertEqual(reason({'status':'completed','row':{'title':'真实标题','video_content':'  '}}),'empty_subtitle')
    def test_typo_is_not_selected(self):
        self.assertIsNone(reason({'status':'completed','row':{'video_content':'78坡三坡两维'}}))
    def test_internal_pollution_is_selected(self):
        self.assertEqual(reason({'status':'completed','row':{'video_content':'全国地产设计产品力监测'}}),'confirmed_internal_context_pollution')
    def test_running_is_not_touched(self):
        self.assertIsNone(reason({'status':'running','row':{'video_content':''}}))
    def test_explicit_missing_is_selected(self):
        self.assertEqual(reason({'subtitle_incomplete_confirmed':True,'row':{'video_content':'已有部分口播'}}),'explicitly_confirmed_subtitle_issue')
    def test_short_text_is_not_inferred_missing(self):
        self.assertIsNone(reason({'row':{'video_content':'你好'}}))
    def test_unknown_identity_is_not_invented(self):
        self.assertIsNone(reason({'status':'retry_pending'}))
if __name__=='__main__': unittest.main()
