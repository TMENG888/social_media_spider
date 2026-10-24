"""Offline failure injection; real Windows process/file tests use only own fixtures."""
import contextlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

COMMON = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(COMMON / 'src'))
from audio_process_guard import cleanup_audio_file, stop_owned_recorder, NativeRecorderJob

source = Path(os.environ.get('CHANNELS_REGRESSION_SOURCE', COMMON / 'src/channels_pc_collector.py'))
spec = importlib.util.spec_from_file_location('channels_lifecycle_test_collector', source)
collector = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = collector
spec.loader.exec_module(collector)


class Clock:
    now = 0
    def sleep(self, seconds):
        self.now += seconds
    def monotonic(self):
        return self.now


def events(output):
    return [json.loads(line) for line in output.getvalue().splitlines() if line.startswith('{')]


class AudioLifecycleRegression(unittest.TestCase):
    def setUp(self):
        collector.STOP_REQUESTED = False

    def watchdog(self, progress, config=None):
        clock = Clock()
        recorder = MagicMock()
        recorder.poll.side_effect = [None] * len(progress) + [0]
        output = io.StringIO()
        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(contextlib.redirect_stdout(output))
        stack.enter_context(patch.object(collector.time, 'sleep', side_effect=clock.sleep))
        stack.enter_context(patch.object(collector.time, 'monotonic', side_effect=clock.monotonic))
        stack.enter_context(patch.object(collector, 'get_video_detail_window', return_value=MagicMock()))
        stack.enter_context(patch.object(collector, 'read_active_video_progress', side_effect=progress))
        stack.enter_context(patch.object(collector, 'ensure_video_playing', return_value=(True, 'already_playing')))
        options = {'client_asr_playback_watchdog_interval_seconds': 0.5,
                   'client_asr_playback_stall_seconds': 1, 'client_asr_playback_max_recoveries': 1}
        options.update(config or {})
        return recorder, options, output

    def test_pause_icon_is_not_recovery_without_clock_advance(self):
        recorder, config, output = self.watchdog([(82, 136)] * 8)
        with self.assertRaises(collector.ClientAudioCaptureError):
            collector.monitor_video_playback_during_capture(recorder, 136, config)
        logs = events(output)
        self.assertFalse(any(e.get('recovered') is True for e in logs))
        self.assertTrue(any(e.get('verification') == 'timeline_stalled' for e in logs))

    def test_recovery_requires_and_accepts_clock_advance(self):
        recorder, config, output = self.watchdog([(82, 136)] * 3 + [(83, 136), (136, 136)])
        audit = collector.monitor_video_playback_during_capture(recorder, 136, config)
        self.assertTrue(audit['coverageComplete'])
        self.assertTrue(any(e.get('verification') == 'timeline_advanced' and e['recovered'] for e in events(output)))

    def test_stop_file_cancels_recording_not_another_audio_retry(self):
        with tempfile.TemporaryDirectory() as folder:
            stop = Path(folder) / 'stop.requested'
            stop.touch()
            recorder, config, _ = self.watchdog([(82, 136)] * 4, {'_capture_stop_file': stop})
            with self.assertRaisesRegex(collector.ClientAudioCaptureError, 'STOP_REQUESTED'):
                collector.monitor_video_playback_during_capture(recorder, 136, config)

    def test_identity_failure_keeps_typed_cause(self):
        recorder, config, _ = self.watchdog([(82, 136)] * 4, {'_capture_identity': {'title': 'target'}})
        with patch.object(collector, 'active_video_records', return_value=[]), patch.object(
            collector, 'video_detail_identity_match', return_value=(False, 0.0, 'other')
        ), self.assertRaises(collector.VideoDetailIdentityMismatchError):
            collector.monitor_video_playback_during_capture(recorder, 136, config)

    def test_reload_already_zero_succeeds_without_slider(self):
        with patch.object(collector, 'read_active_video_progress', return_value=(0, 257)):
            self.assertTrue(collector.seek_active_video_to_start(MagicMock()))

    def test_missing_pycaw_is_one_warning_and_not_audio_success(self):
        collector._AUDIO_SESSION_IMPORT_WARNING_EMITTED = False
        output = io.StringIO()
        with patch.dict(sys.modules, {'pycaw.pycaw': None}), contextlib.redirect_stdout(output):
            first = collector.ensure_wechat_audio_session_unmuted()
            second = collector.ensure_wechat_audio_session_unmuted()
        self.assertEqual(first['matched'], 0)
        self.assertTrue(first['error'])
        self.assertTrue(second['error'])
        self.assertEqual(len(events(output)), 1)
        self.assertEqual(events(output)[0]['errorCode'], 'DEPENDENCY_MISSING')

    def test_unverified_pause_does_not_start_comment_callback_or_recorder(self):
        callback = MagicMock()
        with patch.object(collector, 'prepare_video_detail', side_effect=lambda surface, config: surface), patch.object(
            collector, 'pause_active_video_if_running', return_value=False), patch.object(
            collector.subprocess, 'Popen'
        ) as launch:
            with self.assertRaisesRegex(collector.ClientAudioCaptureError, 'paused target'):
                collector.capture_client_audio_asr('fixture', MagicMock(), {}, duration_seconds=8,
                                                  during_capture_callback=callback)
        callback.assert_not_called()
        launch.assert_not_called()

    def test_seek_action_without_zero_clock_is_not_success(self):
        if not hasattr(collector, '_seek_active_video_to_start_once'):
            self.fail('Missing verified-seek wrapper')
        with patch.object(collector, '_seek_active_video_to_start_once', return_value=True), patch.object(
            collector, 'read_active_video_progress', return_value=(12, 257)
        ), patch.object(collector, 'get_video_detail_window', return_value=MagicMock()), patch.object(collector.time, 'sleep'):
            self.assertFalse(collector.seek_active_video_to_start(MagicMock()))

    def test_comment_work_finishes_before_recorder_launch(self):
        order = []
        recorder = MagicMock()
        recorder.poll.return_value = 0
        recorder.communicate.return_value = (json.dumps({'peak': 0.5, 'rms': 0.1}), '')
        recorder.returncode = 0
        def launch(*args, **kwargs):
            self.assertEqual(order, ['comments'])
            order.append('recorder')
            return recorder
        with tempfile.TemporaryDirectory() as folder, patch.object(
            collector, 'prepare_video_detail', side_effect=lambda surface, config: surface
        ), patch.object(
            collector, 'pause_active_video_if_running', return_value=True
        ), patch.object(collector, 'get_video_detail_window', return_value=MagicMock()), patch.object(
            collector, 'active_video_root', return_value=MagicMock()
        ), patch.object(collector, 'click_named_surface_control', return_value=True), patch.object(
            collector, 'seek_active_video_to_start', return_value=True
        ), patch.object(collector, 'ensure_wechat_audio_session_unmuted', return_value={}), patch.object(
            collector, 'loopback_recorder_command', return_value=(['fixture-recorder'], 'windows_process_loopback', 123)
        ), patch.object(collector.subprocess, 'Popen', side_effect=launch), patch.object(
            collector, 'wait_for_loopback_recorder_ready', return_value={'ready': True}
        ), patch.object(collector, 'ensure_video_audio_unmuted', return_value=(True, 'fixture')), patch.object(
            collector, 'ensure_video_playing', return_value=(True, 'fixture')
        ), patch.object(collector, 'monitor_video_playback_during_capture', return_value={'coverageComplete': True}), patch.object(
            collector, 'truncate_wav_duration', return_value=9.0
        ):
            pending, duration = collector.capture_client_audio_asr('fixture', MagicMock(), {
                'enable_wechat_media_cache': False, 'client_asr_temp_dir': folder,
                'client_asr_audio_preflight_seconds': 0, 'client_asr_background': True,
            }, duration_seconds=8, during_capture_callback=lambda: order.append('comments'))
            self.assertEqual(order, ['comments', 'recorder'])
            self.assertEqual(duration, 8)
            self.assertIsInstance(pending, collector.PendingClientAsr)

    def test_comment_panel_not_ready_retries_and_never_confirms_empty(self):
        config = {'comment_panel_open_attempts': 2}
        surface = MagicMock()
        surface.descendants.return_value = []
        with patch.object(collector, 'get_video_detail_window', return_value=surface), patch.object(
            collector, 'open_video_comments_panel', return_value=False
        ) as opening:
            self.assertEqual(collector.collect_video_comments(surface, config, expected_count=3), [])
        self.assertEqual(opening.call_count, 2)
        self.assertEqual(config['_comment_capture_audit']['status'], 'unavailable')
        self.assertFalse(config['_comment_capture_audit']['emptyConfirmed'])

    def test_ready_panel_without_entries_is_incomplete_not_empty(self):
        config = {'comment_scroll_rounds': 1}
        surface = MagicMock()
        surface.descendants.return_value = []
        surface.rectangle.return_value = SimpleNamespace(left=0, top=0, right=1000, bottom=800)
        with patch.object(collector, 'get_video_detail_window', return_value=surface), patch.object(
            collector, 'open_video_comments_panel', return_value=True
        ), patch.object(collector, 'parse_new_comment_panel', return_value=([], None)), patch.object(
            collector, 'expand_visible_comment_replies', return_value=0
        ), patch.object(collector.time, 'sleep'), patch.object(collector.mouse, 'scroll'):
            self.assertEqual(collector.collect_video_comments(surface, config, expected_count=9), [])
        self.assertEqual(config['_comment_capture_audit']['status'], 'incomplete')

    def test_explicit_empty_conflicting_with_positive_count_is_not_confirmed(self):
        if not hasattr(collector, 'comment_panel_empty_confirmed'):
            self.fail('Missing explicit empty verification')
        config = {}
        with patch.object(collector, 'get_video_detail_window'), patch.object(
            collector, 'open_video_comments_panel', return_value=True
        ), patch.object(collector, 'comment_panel_empty_confirmed', return_value=True):
            self.assertEqual(collector.collect_video_comments(MagicMock(), config, expected_count=3), [])
        self.assertEqual(config['_comment_capture_audit']['status'], 'incomplete')

    def test_explicit_empty_without_positive_count_is_confirmed(self):
        if not hasattr(collector, 'comment_panel_empty_confirmed'):
            self.fail('Missing explicit empty verification')
        config = {}
        with patch.object(collector, 'get_video_detail_window'), patch.object(
            collector, 'open_video_comments_panel', return_value=True
        ), patch.object(collector, 'comment_panel_empty_confirmed', return_value=True):
            collector.collect_video_comments(MagicMock(), config)
        self.assertTrue(config['_comment_capture_audit']['emptyConfirmed'])


class RecorderCleanupTests(unittest.TestCase):
    def test_locked_cleanup_is_bounded_and_preserves_original_error(self):
        logs, pauses = [], []
        with patch.object(Path, 'unlink', side_effect=PermissionError('fixture locked')):
            with self.assertRaisesRegex(ValueError, 'original identity mismatch'):
                try:
                    raise ValueError('original identity mismatch')
                finally:
                    self.assertFalse(cleanup_audio_file('fixture.wav', pause=pauses.append, log=logs.append))
        self.assertEqual(len(pauses), 4)
        self.assertEqual(logs[-1]['event'], 'audio_temp_cleanup_deferred')

    def test_temporary_lock_recovers(self):
        with patch.object(Path, 'unlink', side_effect=[PermissionError(), None]) as unlink:
            self.assertTrue(cleanup_audio_file('fixture.wav', pause=lambda _: None))
        self.assertEqual(unlink.call_count, 2)

    @unittest.skipUnless(os.name == 'nt', 'Windows exclusive file semantics')
    def test_real_native_style_child_lock_is_released_by_tree_cleanup(self):
        # Own dummy Python tree only; no audio devices, platforms, Redis or DB.
        with tempfile.TemporaryDirectory() as folder:
            lockfile, ready, pidfile = [Path(folder) / name for name in ('fixture.wav', 'ready', 'pid')]
            child = (
                "import ctypes,time,sys;from pathlib import Path;"
                "k=ctypes.WinDLL('kernel32',use_last_error=True);"
                "k.CreateFileW.argtypes=[ctypes.c_wchar_p,ctypes.c_uint32,ctypes.c_uint32,ctypes.c_void_p,ctypes.c_uint32,ctypes.c_uint32,ctypes.c_void_p];"
                "k.CreateFileW.restype=ctypes.c_void_p;"
                "h=k.CreateFileW(sys.argv[1],0x40000000,0,None,2,0,None);"
                "assert h not in (None,ctypes.c_void_p(-1).value);"
                "Path(sys.argv[2]).touch();time.sleep(45)"
            )
            parent_code = (
                "import subprocess,sys,time;from pathlib import Path;"
                "p=subprocess.Popen([sys.executable,'-c',sys.argv[1],sys.argv[2],sys.argv[3]]);"
                "Path(sys.argv[4]).write_text(str(p.pid));time.sleep(45)"
            )
            parent = subprocess.Popen([sys.executable, '-c', parent_code, child, str(lockfile), str(ready), str(pidfile)],
                                      creationflags=subprocess.CREATE_NO_WINDOW)
            try:
                deadline = time.monotonic() + 15
                while not ready.exists() and time.monotonic() < deadline:
                    time.sleep(0.05)
                self.assertTrue(ready.exists(), 'Fixture child did not acquire exclusive handle')
                with self.assertRaises(PermissionError):
                    lockfile.unlink()
                self.assertTrue(stop_owned_recorder(parent))
                self.assertIsNotNone(parent.poll())
                self.assertTrue(cleanup_audio_file(lockfile))
                self.assertFalse(lockfile.exists())
            finally:
                stop_owned_recorder(parent)

    @unittest.skipUnless(os.name == 'nt', 'Windows Job Object')
    def test_job_close_kills_only_owned_native_process(self):
        with NativeRecorderJob() as job:
            child = job.spawn([sys.executable, '-c', 'import time;time.sleep(45)'],
                              creationflags=subprocess.CREATE_NO_WINDOW)
            self.assertIsNone(child.poll())
        child.wait(timeout=5)
        self.assertIsNotNone(child.returncode)

    @unittest.skipUnless(os.name == 'nt' and (COMMON / 'src/process-loopback-recorder.exe').exists(),
                         'Native process-loopback-recorder.exe absent; do not substitute endpoint capture')
    def test_real_shipped_recorder_rejects_silent_fixture_and_releases_file(self):
        with tempfile.TemporaryDirectory() as folder:
            wav = Path(folder) / 'silent-fixture.wav'
            target = subprocess.Popen([sys.executable, '-c', 'import time;time.sleep(30)'],
                                      creationflags=subprocess.CREATE_NO_WINDOW)
            recorder = None
            try:
                recorder = subprocess.Popen([
                    sys.executable, '-B', str(COMMON / 'src/loopback-recorder.py'),
                    '--duration', '2', '--process-id', str(target.pid),
                    '--initial-silence-seconds', '0', '--output', str(wav),
                ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8',
                    errors='replace', creationflags=subprocess.CREATE_NO_WINDOW)
                stdout, stderr = recorder.communicate(timeout=20)
                self.assertIn('windows_process_loopback', stdout)
                self.assertNotEqual(recorder.returncode, 0)
                self.assertIn('回采为空', stderr)
                self.assertNotIn('WinError 32', stderr)
                self.assertTrue(cleanup_audio_file(wav))
            finally:
                stop_owned_recorder(recorder)
                stop_owned_recorder(target)

    @unittest.skipUnless(os.name == 'nt' and (COMMON / 'src/process-loopback-recorder.exe').exists(),
                         'Native process-loopback-recorder.exe absent; do not substitute endpoint capture')
    def test_real_shipped_recorder_tree_abort_releases_exclusive_wav(self):
        with tempfile.TemporaryDirectory() as folder:
            wav = Path(folder) / 'abort-fixture.wav'
            target = subprocess.Popen([sys.executable, '-c', 'import time;time.sleep(30)'],
                                      creationflags=subprocess.CREATE_NO_WINDOW)
            recorder = None
            try:
                recorder = subprocess.Popen([
                    sys.executable, '-B', str(COMMON / 'src/loopback-recorder.py'),
                    '--duration', '20', '--process-id', str(target.pid),
                    '--initial-silence-seconds', '0', '--output', str(wav),
                ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8',
                    errors='replace', creationflags=subprocess.CREATE_NO_WINDOW)
                deadline = time.monotonic() + 10
                while not wav.exists() and recorder.poll() is None and time.monotonic() < deadline:
                    time.sleep(0.05)
                self.assertTrue(wav.exists(), 'Real native writer did not start')
                with self.assertRaises(PermissionError):
                    wav.unlink()
                self.assertTrue(stop_owned_recorder(recorder))
                self.assertTrue(cleanup_audio_file(wav))
                self.assertFalse(wav.exists())
                # The synthetic target is not a recorder descendant and survives.
                self.assertIsNone(target.poll())
            finally:
                stop_owned_recorder(recorder)
                stop_owned_recorder(target)

    @unittest.skipUnless(os.name == 'nt', 'Windows abnormal-wrapper-exit integration')
    def test_wrapper_termination_closes_job_and_releases_real_writer(self):
        with tempfile.TemporaryDirectory() as folder:
            wav, ready = [Path(folder) / name for name in ('native-style.wav', 'ready')]
            writer = (
                "import ctypes,time,sys;from pathlib import Path;"
                "k=ctypes.WinDLL('kernel32',use_last_error=True);"
                "k.CreateFileW.argtypes=[ctypes.c_wchar_p,ctypes.c_uint32,ctypes.c_uint32,ctypes.c_void_p,ctypes.c_uint32,ctypes.c_uint32,ctypes.c_void_p];"
                "k.CreateFileW.restype=ctypes.c_void_p;"
                "h=k.CreateFileW(sys.argv[1],0x40000000,0,None,2,0,None);"
                "assert h not in (None,ctypes.c_void_p(-1).value);"
                "Path(sys.argv[2]).touch();time.sleep(30)"
            )
            wrapper_code = (
                "import sys,time;sys.path.insert(0,sys.argv[1]);"
                "from audio_process_guard import NativeRecorderJob;"
                "job=NativeRecorderJob();job.__enter__();"
                "p=job.spawn([sys.executable,'-c',sys.argv[2],sys.argv[3],sys.argv[4]]);time.sleep(30)"
            )
            wrapper = subprocess.Popen([sys.executable, '-c', wrapper_code, str(COMMON / 'src'),
                                        writer, str(wav), str(ready)], creationflags=subprocess.CREATE_NO_WINDOW)
            try:
                deadline = time.monotonic() + 10
                while not ready.exists() and wrapper.poll() is None and time.monotonic() < deadline:
                    time.sleep(0.05)
                self.assertTrue(ready.exists())
                with self.assertRaises(PermissionError):
                    wav.unlink()
                wrapper.terminate()  # Simulates abrupt wrapper death, no Python finally.
                wrapper.wait(timeout=5)
                self.assertTrue(cleanup_audio_file(wav))
                self.assertFalse(wav.exists())
            finally:
                stop_owned_recorder(wrapper)


if __name__ == '__main__':
    unittest.main(verbosity=2)
