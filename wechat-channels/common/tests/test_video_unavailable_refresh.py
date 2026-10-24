import ast
import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

COMMON = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(COMMON / 'src'))
import channels_pc_collector as c
import precise_video_retry as direct

TITLE = '测试住宅视频的完整目标标题'
CARD = {'title': TITLE, 'author_name': '作者甲'}
RECT = SimpleNamespace(left=0, top=0, right=800, bottom=600)


class Control:
    def __init__(self, name, kind='Text', cls='', visible=True, rect=RECT):
        self.element_info = SimpleNamespace(name=name, control_type=kind, class_name=cls)
        self.visible, self.rect = visible, rect
    def window_text(self):
        return self.element_info.name
    def rectangle(self):
        return self.rect
    def is_visible(self):
        return self.visible


class Surface:
    def __init__(self, state, *, title=TITLE, extra=()):
        self.state, self.title, self.extra = state, title, extra
        self.set_focus = Mock()
    def rectangle(self):
        return RECT
    def descendants(self, control_type=None):
        controls = [Control(self.title), Control('作者甲'), *self.extra]
        if self.state == 'blocked':
            controls += [Control('暂无法观看此视频，可尝试切换网络或检查是否配置了代理')]
        elif self.state == 'login':
            controls += [Control('扫码登录', 'Button')]
        elif self.state == 'captcha':
            controls += [Control('请完成安全验证')]
        if self.state in {'ready', 'blocked', 'login', 'captcha'}:
            # Even on a failed player, action metadata can already exist.
            controls += [Control(str(i), 'Button', 'op-item') for i in range(4)]
        return [v for v in controls if control_type is None or v.element_info.control_type == control_type]


class Harness:
    def __init__(self, states):
        self.surfaces = [v if isinstance(v, Surface) else Surface(v) for v in states]
        self.index, self.now = 0, 0.0
        self.keyboard, self.report = Mock(), Mock()
        self.keyboard.send_keys.side_effect = self.reload
        self.after_wait = lambda: None
    def reload(self, *args, **kwargs):
        self.index = min(self.index + 1, len(self.surfaces) - 1)
    def get(self, **kwargs):
        return self.surfaces[self.index]
    def wait(self, seconds):
        self.now += max(0.01, seconds)
        self.after_wait()
        return not c.STOP_REQUESTED
    def __enter__(self):
        self.patches = patch.multiple(c,
            active_video_root=lambda s: s,
            active_video_records=lambda s: [(x.window_text(), x.element_info.control_type,
                                            x.element_info.class_name) for x in s.descendants()],
            get_video_detail_window=self.get,
            is_video_detail_page=lambda s: True,
            pause_active_video_if_running=Mock(return_value=True),
            keyboard=self.keyboard, report_from_environment=self.report,
            interruptible_wait=self.wait, STOP_REQUESTED=False)
        self.patches.start()
        self.clock = patch.object(c.time, 'monotonic', side_effect=lambda: self.now)
        self.clock.start()
        self.output = io.StringIO()
        self.stdout = redirect_stdout(self.output)
        self.stdout.__enter__()
        return self
    def __exit__(self, *args):
        self.stdout.__exit__(*args)
        self.clock.stop()
        self.patches.stop()
    def run(self, **config):
        return c.prepare_video_detail(self.get(),
            dict(wait_video_detail_ready_seconds=1,
                 video_unavailable_refresh_backoff_seconds=0.5, **config),
            CARD, keyword='隔离测试', result_index=7)


class RefreshTests(unittest.TestCase):
    def test_healthy_video_never_refreshes(self):
        with Harness(['ready']) as h:
            self.assertIs(h.run(), h.get())
            h.keyboard.send_keys.assert_not_called()

    def test_spontaneous_recovery_during_backoff_avoids_extra_refresh(self):
        with Harness(['blocked', 'ready']) as h:
            h.after_wait = lambda: setattr(h, 'index', 1)
            h.run()
            h.keyboard.send_keys.assert_not_called()

    def test_login_dialog_outside_feed_item_still_blocks_refresh(self):
        with Harness(['login']) as h, patch.object(c, 'active_video_root', return_value=Surface('blocked')):
            with self.assertRaisesRegex(c.VideoDetailRecoveryBlockedError, 'STOP_LOGIN_REQUIRED'):
                h.run()
            h.keyboard.send_keys.assert_not_called()

    def test_detail_disappearing_during_backoff_is_retryable_not_content_failure(self):
        with Harness(['blocked']) as h:
            with patch.object(c, 'get_video_detail_window', side_effect=c.SearchWindowUnavailableError('gone')):
                with self.assertRaises(c.VideoPlaybackUnavailableError):
                    h.run()
            h.keyboard.send_keys.assert_not_called()

    def test_one_refresh_recovers_same_video(self):
        with Harness(['blocked', 'ready']) as h:
            self.assertIs(h.run(), h.get())
            h.keyboard.send_keys.assert_called_once_with('^r', pause=0.02)
            self.assertIn('video_unavailable_refresh_recovered', h.output.getvalue())
            self.assertIn('"identityVerified": true', h.output.getvalue())

    def test_multiple_refreshes_before_recovery(self):
        with Harness(['blocked', 'blocked', 'blocked', 'ready']) as h:
            h.run()
            self.assertEqual(h.keyboard.send_keys.call_count, 3)
            self.assertGreaterEqual(h.now, 6)

    def test_default_fourth_refresh_can_recover(self):
        with Harness(['blocked'] * 4 + ['ready']) as h:
            h.run()
            self.assertEqual(h.keyboard.send_keys.call_count, 4)

    def test_refresh_exhaustion_does_not_treat_action_buttons_as_success(self):
        with Harness(['blocked']) as h:
            with self.assertRaises(c.VideoPlaybackUnavailableError):
                h.run(video_unavailable_refresh_attempts=3)
            self.assertEqual(h.keyboard.send_keys.call_count, 3)
            self.assertNotIn('refresh_recovered', h.output.getvalue())

    def test_disable_and_hard_cap(self):
        for configured, expected in [(0, 0), (999, 10)]:
            with self.subTest(configured=configured), Harness(['blocked']) as h:
                with self.assertRaises(c.VideoPlaybackUnavailableError):
                    h.run(video_unavailable_refresh_attempts=configured)
                self.assertEqual(h.keyboard.send_keys.call_count, expected)

    def test_blank_after_refresh_is_not_recovered(self):
        with Harness(['blocked', 'loading']) as h:
            with self.assertRaises(c.VideoPlaybackUnavailableError):
                h.run(video_unavailable_refresh_attempts=1)
            self.assertNotIn('refresh_recovered', h.output.getvalue())

    def test_wrong_video_after_refresh_is_rejected(self):
        with Harness(['blocked', Surface('ready', title='另一个毫不相关的视频')]) as h:
            with self.assertRaises(c.VideoDetailIdentityMismatchError):
                h.run()
            self.assertNotIn('refresh_recovered', h.output.getvalue())

    def test_refresh_without_expected_identity_cannot_claim_recovery(self):
        with Harness(['blocked', 'ready']) as h:
            with self.assertRaises(c.VideoDetailIdentityMismatchError):
                c.prepare_video_detail(h.get(), {'wait_video_detail_ready_seconds': 1})
            self.assertNotIn('refresh_recovered', h.output.getvalue())

    def test_login_and_captcha_are_not_refreshed(self):
        for state in ('login', 'captcha'):
            with self.subTest(state=state), Harness([state]) as h:
                with self.assertRaisesRegex(RuntimeError, 'STOP_'):
                    h.run()
                h.keyboard.send_keys.assert_not_called()
                h.report.assert_called_once()

    def test_gate_appearing_after_reload_stops_further_reloads(self):
        with Harness(['blocked', 'login']) as h:
            with self.assertRaisesRegex(RuntimeError, 'STOP_LOGIN_REQUIRED'):
                h.run()
            self.assertEqual(h.keyboard.send_keys.call_count, 1)

    def test_signal_before_and_during_backoff(self):
        for immediate in (True, False):
            with self.subTest(immediate=immediate), Harness(['blocked']) as h:
                if immediate:
                    c.STOP_REQUESTED = True
                else:
                    h.after_wait = lambda: setattr(c, 'STOP_REQUESTED', True)
                with self.assertRaisesRegex(c.ClientAudioCaptureError, 'STOP_REQUESTED'):
                    h.run()
                h.keyboard.send_keys.assert_not_called()

    def test_worker_stop_file_interrupts_backoff(self):
        with tempfile.TemporaryDirectory() as folder, Harness(['blocked']) as h:
            stop = Path(folder) / 'stop.requested'
            h.after_wait = lambda: stop.touch()
            with self.assertRaisesRegex(c.ClientAudioCaptureError, 'STOP_REQUESTED'):
                h.run(_capture_stop_file=stop)
            h.keyboard.send_keys.assert_not_called()

    def test_hidden_offscreen_and_caption_substring_are_not_player_error(self):
        for extra in (
            Control('暂无法观看此视频', visible=False),
            Control('暂无法观看此视频', rect=SimpleNamespace(left=0, right=800, top=700, bottom=900)),
            Control('有人说暂无法观看此视频，可以试试刷新'),
        ):
            with self.subTest(label=extra.window_text()), Harness([Surface('ready', extra=[extra])]) as h:
                h.run()
                h.keyboard.send_keys.assert_not_called()

    def test_disappeared_detail_is_not_refreshed_again(self):
        with Harness(['blocked']) as h:
            original = h.get
            def getter(**kwargs):
                if h.keyboard.send_keys.call_count:
                    raise c.SearchWindowUnavailableError('navigation gap')
                return original(**kwargs)
            with patch.object(c, 'get_video_detail_window', side_effect=getter):
                with self.assertRaises(c.VideoPlaybackUnavailableError):
                    h.run()
            self.assertEqual(h.keyboard.send_keys.call_count, 1)

    def test_no_network_error_does_not_refresh_generic_slow_page(self):
        with Harness(['loading']) as h:
            with self.assertRaisesRegex(RuntimeError, '互动栏'):
                h.run()
            h.keyboard.send_keys.assert_not_called()

    def test_optional_audio_must_not_swallow_network_recovery_exhaustion(self):
        error = c.ClientAudioCaptureError('wrapped')
        error.__cause__ = c.VideoPlaybackUnavailableError('refresh exhausted')
        with patch.dict(os.environ, SOCIAL_VOLUME_ENABLED='1'), patch.object(
                c, 'capture_client_audio_asr', side_effect=error):
            with self.assertRaises(c.ClientAudioCaptureError):
                c.capture_primary_audio_optional(duration_seconds=30)

    def test_direct_retry_exhaustion_keeps_checkpoint_without_search_fallback(self):
        adapter = SimpleNamespace(
            load_video_checkpoints=lambda *args: {'abc': {'row': {
                'url': 'https://weixin.qq.com/sph/Test', **CARD}}},
            is_valid_channels_share_url=lambda _: True,
            prepare_video_detail=Mock(side_effect=c.VideoPlaybackUnavailableError('exhausted')),
            VideoPlaybackUnavailableError=c.VideoPlaybackUnavailableError,
            return_to_search_results=Mock(), upsert_video_checkpoint=Mock())
        with patch.object(direct, 'open_saved_video', return_value=object()), patch.object(
                direct, 'verify_target') as verify:
            result = direct.try_direct_retry(adapter, '测试', '专题一', 'abc', {}, None, None, False)
        self.assertFalse(result['complete'])
        self.assertEqual(result['reason'], 'VIDEO_PLAYBACK_UNAVAILABLE')
        verify.assert_not_called()
        adapter.upsert_video_checkpoint.assert_not_called()

    def test_live_and_recording_entrypoints_use_recovery_before_recorder(self):
        source = (COMMON / 'src/channels_pc_collector.py').read_text(encoding='utf-8-sig')
        tree = ast.parse(source)
        live = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'collect_live_keyword')
        handlers = [n for n in ast.walk(live) if isinstance(n, ast.ExceptHandler)
                    and n.type is not None and 'VideoPlaybackUnavailableError' in ast.unparse(n.type)]
        self.assertEqual(len(handlers), 1)
        branch = ast.unparse(handlers[0])
        self.assertIn('update_task_state', branch)
        self.assertNotIn('record_video_failure', branch)
        self.assertNotIn('result_index +=', branch)
        capture = source[source.index('def capture_client_audio_asr('):source.index('def volume_export_local_target(')]
        self.assertGreaterEqual(capture.count('prepare_video_detail(surface, config)'), 2)
        loop = capture[capture.index('for audio_attempt in range'):]
        self.assertLess(loop.index('prepare_video_detail('), loop.index('process = subprocess.Popen('))



    def test_new_audio_path_reaches_callback_only_after_same_video_recovers(self):
        callback = Mock(side_effect=ValueError('isolated callback reached'))
        with Harness(['blocked', 'blocked', 'ready']) as h:
            with self.assertRaisesRegex(ValueError, 'isolated callback reached'):
                c.capture_client_audio_asr(TITLE, h.get(),
                    {'wait_video_detail_ready_seconds': 1, '_capture_identity': CARD},
                    duration_seconds=8, during_capture_callback=callback)
            self.assertEqual(h.keyboard.send_keys.call_count, 2)
            callback.assert_called_once()

    def test_direct_gate_does_not_fall_back_to_search(self):
        adapter = SimpleNamespace(
            load_video_checkpoints=lambda *args: {'abc': {'row': {
                'url': 'https://weixin.qq.com/sph/Test', **CARD}}},
            is_valid_channels_share_url=lambda _: True,
            prepare_video_detail=Mock(side_effect=c.VideoDetailRecoveryBlockedError('STOP_LOGIN_REQUIRED')),
            VideoDetailRecoveryBlockedError=c.VideoDetailRecoveryBlockedError,
            return_to_search_results=Mock())
        with patch.object(direct, 'open_saved_video', return_value=object()), self.assertRaisesRegex(
                c.VideoDetailRecoveryBlockedError, 'STOP_LOGIN_REQUIRED'):
            direct.try_direct_retry(adapter, '测试', '专题一', 'abc', {}, None, None, False)

    def test_actual_item_loop_retains_sqlite_cursor_and_content_attempts(self):
        source = COMMON / 'src/channels_pc_collector.py'
        tree = ast.parse(source.read_text(encoding='utf-8-sig'))
        live = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'collect_live_keyword')
        loop = next(n for n in ast.walk(live) if isinstance(n, ast.For)
                    and isinstance(n.target, ast.Name) and n.target.id == 'item_attempt')
        for state in ('blocked', 'login'):
            with self.subTest(state=state), tempfile.TemporaryDirectory() as folder, Harness([state]) as h:
                db = c.init_state(Path(folder) / 'isolated.sqlite')
                try:
                    c.update_task_state(db, '测试', '专题一', 7, 0, 'running')
                    row = c.ResultRow(project='专题一', keyword='测试', title=TITLE,
                                      url='https://weixin.qq.com/sph/Test', author_name='作者甲')
                    c.upsert_video_checkpoint(db, keyword='测试', project='专题一',
                        fingerprint='abc', status='retry_pending', retry_count=2, row=row,
                        asr_status='retry_pending', result_index=7)
                    before = dict(c.load_video_checkpoints(db, '测试')['abc'])
                    result = SimpleNamespace(window_text=lambda: TITLE)
                    failure = Mock()
                    scope = dict(vars(c), connection=db, keyword='测试', project='专题一',
                        result_index=7, old_streak=0, title=TITLE, card=CARD, card_fingerprint='abc',
                        config={'enable_client_asr': False, 'video_unavailable_refresh_attempts': 0},
                        item_attempts_this_run=1, status='running', failed=0,
                        last_item_exception=None, item_success=False,
                        get_search_window=lambda: object(), search_result_buttons=lambda _: [result] * 8,
                        parse_video_card_text=lambda _: {**CARD, 'duration_seconds': 30, 'relative_time': None, 'tags': None},
                        bring_search_result_into_view=lambda *args: result,
                        jitter_pause=lambda *args, **kwargs: True,
                        click_visible_search_result=lambda _: (10, 10),
                        wait_for=lambda predicate, **kwargs: predicate(), has_video_detail_window=lambda: True,
                        return_to_search_results=Mock(), record_video_failure=failure,
                        has_search_window=lambda: False,
                        search_in_web=Mock(side_effect=AssertionError('Unexpected search in isolated fixture')),
                        cleanup_stale_video_windows=Mock())
                    # Keep the production loop in a real enclosing function,
                    # including its nonlocal detail callback bindings.
                    import textwrap
                    assigned = {n.id for n in ast.walk(loop)
                                if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store)}
                    assigned.update(name for n in ast.walk(loop) if isinstance(n, ast.Nonlocal) for name in n.names)
                    wrapper = 'def exercise():\n' + ''.join(
                        f'    {name} = initial.get({name!r})\n' for name in sorted(assigned))
                    wrapper += textwrap.indent(ast.unparse(loop), '    ') + '\n    return locals()\n'
                    scope['initial'] = dict(scope)
                    exec(compile(wrapper, str(source), 'exec'), scope)
                    scope.update(scope['exercise']())
                    self.assertIsInstance(scope['last_item_exception'],
                        (c.VideoPlaybackUnavailableError, c.VideoDetailRecoveryBlockedError))
                    self.assertEqual(scope['result_index'], 7)
                    self.assertEqual(scope['failed'], 0)
                    self.assertFalse(scope['item_success'])
                    failure.assert_not_called()
                    after = c.load_video_checkpoints(db, '测试')['abc']
                    self.assertEqual(after['retry_count'], before['retry_count'])
                    self.assertEqual(after['status'], 'retry_pending')
                    task = db.execute('SELECT next_result_index,status FROM crawl_task WHERE keyword=?', ('测试',)).fetchone()
                    self.assertEqual(tuple(task), (7, 'partial_error'))
                finally:
                    db.close()


if __name__ == '__main__':
    unittest.main(verbosity=2)
