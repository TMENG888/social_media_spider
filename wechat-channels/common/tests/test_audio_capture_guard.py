import ast
import json
import struct
import sys
import tempfile
import unittest
import wave
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

COMMON = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(COMMON / 'src'))
from audio_capture_guard import growing_wav_peak


class AudioGuardTests(unittest.TestCase):
    def test_pcm_peak_and_unfinished_data_length(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'a.wav'
            with wave.open(str(path), 'wb') as stream:
                stream.setnchannels(1)
                stream.setsampwidth(2)
                stream.setframerate(16000)
                stream.writeframes(struct.pack('<hhh', 0, -16384, 100))
            self.assertAlmostEqual(growing_wav_peak(path), 16384 / 32767)
            data = bytearray(path.read_bytes())
            data[40:44] = b'\0' * 4
            path.write_bytes(data)
            self.assertAlmostEqual(growing_wav_peak(path), 16384 / 32767)

    def test_missing_or_invalid_wav_is_unknown_not_silent(self):
        self.assertIsNone(growing_wav_peak('no-such-audio.wav'))
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'a.wav'
            path.write_bytes(b'RIFF')
            self.assertIsNone(growing_wav_peak(path))

    def test_generic_volume_is_not_success_until_waveform(self):
        source = COMMON / 'src/channels_pc_collector.py'
        tree = ast.parse(source.read_text(encoding='utf-8-sig'))
        node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'ensure_video_audio_unmuted')
        rect = SimpleNamespace(left=0, top=0, right=30, bottom=30, width=lambda:30, height=lambda:30)
        button = SimpleNamespace(element_info=SimpleNamespace(name='音量', class_name='', control_type='Button'),
                                 rectangle=lambda:rect, is_visible=lambda:True, click_input=Mock())
        root = SimpleNamespace(rectangle=lambda:rect, descendants=lambda **kwargs:[] if kwargs else [button])
        scope = dict(active_video_root=lambda surface:root, click_named_surface_control=lambda *args:False,
                     mouse=Mock(), time=Mock(), json=json)
        exec(compile(ast.Module(body=[node], type_ignores=[]), str(source), 'exec'), scope)
        ensure = scope['ensure_video_audio_unmuted']
        self.assertEqual(ensure(root), (False, 'uia:音量:state_unknown_no_click'))
        button.click_input.assert_not_called()
        self.assertEqual(ensure(root, assume_audible_from_search_card=True),
                         (False, 'search_card:audio_requested_unverified'))
        button.click_input.assert_not_called()
        self.assertEqual(ensure(root, toggle_generic_volume=True), (True, 'uia:音量'))
        button.click_input.assert_called_once()

    def test_reload_is_preflighted_before_full_recorder(self):
        source = (COMMON / 'src/channels_pc_collector.py').read_text(encoding='utf-8-sig')
        capture = source[source.index('def capture_client_audio_asr('):source.index('def transcribe_pending_client_audio(')]
        loop = capture[capture.index('for audio_attempt in range'):]
        self.assertLess(loop.index('verify_client_audio_before_full_capture('), loop.index('process = subprocess.Popen('))
        self.assertNotIn('toggle_generic_volume=True', capture)
        self.assertNotIn('seeked or seek_active_video_to_start', capture)
        self.assertIn('--initial-silence-seconds', capture)

    def test_seek_anchor_scales_with_time_label(self):
        # Live 150% label height=26, right=466; the actual track starts
        # around x=500, whereas the old fixed offset clicked x=482.
        self.assertGreaterEqual(466 + max(14, round(26 * 1.4)) + 2, 500)
        source = (COMMON / 'src/channels_pc_collector.py').read_text(encoding='utf-8-sig')
        self.assertIn('round(label_rect.height() * 1.4)', source)


if __name__ == '__main__':
    unittest.main()
