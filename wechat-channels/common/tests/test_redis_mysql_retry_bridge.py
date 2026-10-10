import sys,unittest,hashlib
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parents[1]/'src'))
from redis_mysql_retry_bridge import bind_record,confirm_commit
class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.cp={'project':'专题一','article_key':'abc','row':{'author_name':'甲','video_content':'旧值'},'field_completeness':dict.fromkeys(['title','url','author','duration','comments'],True)}
        self.row={'id':'1','文章id':'abc','平台':'微信视频号','项目':'专题一','作者名字':'甲','文章链接':'https://weixin.qq.com/sph/Test','文章视频内容':'新字幕'}
        self.receipt={'id':'1','url':self.row['文章链接'],'committed':True,'readbackVerified':True,'subtitleHash':hashlib.sha256('新字幕'.encode()).hexdigest()}
    def test_binding_preserves_old_text(self):self.assertEqual(bind_record(self.cp,self.row)['row']['video_content'],'旧值')
    def test_no_title_only_matching(self):
        with self.assertRaises(ValueError):bind_record({**self.cp,'article_key':'wrong'},self.row)
    def test_uncommitted_rejected(self):
        with self.assertRaises(ValueError):confirm_commit(self.cp,{**self.receipt,'committed':False},self.row)
    def test_hash_rejected(self):
        with self.assertRaises(ValueError):confirm_commit(self.cp,{**self.receipt,'subtitleHash':'wrong'},self.row)
    def test_other_fields_incomplete(self):
        with self.assertRaises(ValueError):confirm_commit({**self.cp,'field_completeness':{}},self.receipt,self.row)
    def test_verified_commit_completes(self):self.assertEqual(confirm_commit(self.cp,self.receipt,self.row)['status'],'completed')
if __name__=='__main__':unittest.main()
