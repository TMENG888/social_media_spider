import sys
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch, Mock
from types import SimpleNamespace
sys.path.insert(0, str(Path(__file__).parents[1] / 'src'))
import channels_pc_collector as c
from subtitle_review import force_retranscribe, has_internal_prompt
from precise_video_retry import verify_target, try_direct_retry, open_saved_video

class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name) / 'state.sqlite'
        self.conn = c.init_state(self.db)
        self.row = c.ResultRow(project='专题一', keyword='测试', title='真实标题',
                               url='https://weixin.qq.com/sph/Test', video_content='旧字幕已备份之前不能被覆盖', video_duration=30)
        c.save_row(self.conn, self.row)
        self.key = c.article_key_for_row(self.row)
        c.upsert_video_checkpoint(self.conn, keyword='测试', project='专题一',
                                 fingerprint='abc', status='retry_pending', row=self.row, asr_status='retry_pending')
    def tearDown(self):
        self.conn.close()
        self.temp.cleanup()
    def run_queue(self, text):
        wav = Path(self.temp.name) / 'test.wav'
        wav.touch()
        job = c.PendingClientAsr(wav, '真实标题', None, 30, 30, 30, {}, True, False)
        with patch.object(c, 'transcribe_pending_client_audio', return_value=text):
            q = c.BackgroundAsrQueue(self.db, {}, recovery_article_keys=set())
            q.submit(self.key, '测试', job, fingerprint='abc', project='专题一')
            q.close_and_wait()
    def test_short_candidate_preserves_old_and_pending(self):
        self.run_queue('太短')
        self.assertEqual(self.conn.execute('SELECT video_content FROM captured_article').fetchone()[0], self.row.video_content)
        self.assertEqual(self.conn.execute('SELECT status FROM video_checkpoint').fetchone()[0], 'retry_pending')
        self.assertEqual(self.conn.execute('SELECT status FROM asr_candidate').fetchone()[0], 'review')
    def test_approved_candidate_backups_and_replaces(self):
        text = '今天我们走进这套住宅看看客厅和厨房的布局以及房间的采光通风情况。'
        self.run_queue(text)
        self.assertEqual(self.conn.execute('SELECT video_content FROM captured_article').fetchone()[0], text)
        self.assertEqual(self.conn.execute('SELECT old_text FROM subtitle_backup').fetchone()[0], self.row.video_content)
        self.assertEqual(self.conn.execute('SELECT status FROM video_checkpoint').fetchone()[0], 'completed')
    def test_pollution_is_staged_not_committed(self):
        self.run_queue('全国地产设计产品力监测' + '这套住宅的各个房间都有充足的采光和舒适通风。')
        self.assertEqual(self.conn.execute('SELECT video_content FROM captured_article').fetchone()[0], self.row.video_content)
    def test_no_text_is_not_completed(self):
        self.run_queue(None)
        self.assertEqual(self.conn.execute('SELECT status FROM video_checkpoint').fetchone()[0], 'retry_pending')
    def test_long_title_does_not_allow_wrong_author(self):
        result = c.video_detail_identity_match('这是完全一致的很长的视频标题', '作者甲',
            [('这是完全一致的很长的视频标题', 'Text', 'desc'), ('作者乙', 'Text', 'author')])
        self.assertFalse(result[0])
    def test_pollution_forces_retranscribe(self):
        self.assertTrue(force_retranscribe({}, {'row':{'video_content':'全国地产设计产品力监测'}}))
    def test_url_target_requires_author_and_duration(self):
        adapter = SimpleNamespace(
            active_video_records=lambda _: [('真实标题长一点的目标视频','Text','desc'),('作者甲','Text','author')],
            parse_article_details=lambda _: {'author_name':'作者甲'},
            video_detail_identity_match=c.video_detail_identity_match,
            resolve_video_detail_duration=lambda *args: 30)
        cp={'row':{'title':'真实标题长一点的目标视频','author_name':'作者甲','video_duration':30}}
        self.assertEqual(verify_target(adapter, object(), cp)[4],30)
        cp['row']['author_name']='作者乙'
        with self.assertRaises(RuntimeError):
            verify_target(adapter, object(), cp)
        cp['row']['author_name']='作者甲'
        cp['row']['video_duration']=60
        with self.assertRaises(RuntimeError):
            verify_target(adapter, object(), cp)
    def test_url_without_identity_is_not_invented(self):
        adapter = SimpleNamespace(active_video_records=lambda _: [],
            parse_article_details=lambda _: {})
        with self.assertRaisesRegex(RuntimeError, 'identity_recovery_required'):
            verify_target(adapter, object(), {'row':{'url':'https://weixin.qq.com/sph/Test'}})

    def test_direct_without_url_uses_search_fallback(self):
        adapter = SimpleNamespace(load_video_checkpoints=lambda *args: {'abc': {'row': {}}})
        self.assertIsNone(try_direct_retry(adapter, '测试', '专题一', 'abc', {}, self.conn, None, False))

    def test_wrong_direct_identity_closes_before_search_fallback(self):
        closer = Mock()
        adapter = SimpleNamespace(
            load_video_checkpoints=lambda *args: {'abc': {'row': {'url':'https://weixin.qq.com/sph/Test'}}},
            is_valid_channels_share_url=lambda _: True,
            return_to_search_results=closer)
        with patch('precise_video_retry.open_saved_video', return_value=object()), patch(
            'precise_video_retry.verify_target', side_effect=RuntimeError('wrong author')):
            self.assertIsNone(try_direct_retry(adapter, '测试', '专题一', 'abc', {}, self.conn, None, False))
        closer.assert_called_once_with({})

    def test_failed_direct_cleanup_cannot_open_another_window(self):
        adapter = SimpleNamespace(
            load_video_checkpoints=lambda *args: {'abc': {'row': {'url':'https://weixin.qq.com/sph/Test'}}},
            is_valid_channels_share_url=lambda _: True,
            return_to_search_results=Mock(side_effect=RuntimeError('cannot close detail')))
        with patch('precise_video_retry.open_saved_video', return_value=object()), patch(
            'precise_video_retry.verify_target', side_effect=RuntimeError('wrong author')):
            with self.assertRaisesRegex(RuntimeError, 'cannot close detail'):
                try_direct_retry(adapter, '测试', '专题一', 'abc', {}, self.conn, None, False)

    def test_collapsed_url_edit_expands_before_click(self):
        def rect(left, top, right, bottom):
            return SimpleNamespace(left=left,top=top,right=right,bottom=bottom)
        expanded = [False]
        edit = Mock()
        edit.rectangle.side_effect=lambda: rect(843,9,1161,41) if expanded[0] else rect(1290,9,1320,41)
        minimize = Mock()
        minimize.window_text.return_value='最小化'
        minimize.rectangle.return_value=rect(1162,9,1194,41)
        web = Mock()
        web.rectangle.return_value=rect(0,0,1266,665)
        web.descendants.side_effect=lambda control_type: [edit] if control_type=='Edit' else [minimize]
        def expand(**kwargs):
            self.assertEqual(kwargs['coords'], (1146,25))
            expanded[0]=True
        def wait(predicate, **kwargs):
            self.assertTrue(predicate())
        adapter=SimpleNamespace(is_valid_channels_share_url=lambda _:True,
            get_search_window=lambda **kwargs:web,mouse=SimpleNamespace(click=expand),
            wait_for=wait,has_video_detail_window=lambda:True,
            get_video_detail_window=lambda **kwargs:object(),pause_active_video_if_running=Mock(),
            set_clipboard=Mock(),keyboard=SimpleNamespace(send_keys=Mock()))
        open_saved_video(adapter,'https://weixin.qq.com/sph/Test',{})
        self.assertTrue(expanded[0])
        edit.click_input.assert_called_once()

if __name__ == '__main__':
    unittest.main()
