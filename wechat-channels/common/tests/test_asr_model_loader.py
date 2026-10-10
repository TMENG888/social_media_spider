import importlib.util
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from unittest.mock import Mock

SRC = Path(__file__).resolve().parents[1] / 'src'
sys.path.insert(0, str(SRC))
spec = importlib.util.spec_from_file_location('asr_model_loader', SRC/'asr_model_loader.py')
loader = importlib.util.module_from_spec(spec)
spec.loader.exec_module(loader)


class ModelDownloadTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.model = Path(self.temp.name)/'snapshot'
        self.model.mkdir()
        for name in ('model.bin', 'tokenizer.json', 'vocabulary.txt'):
            (self.model/name).write_bytes(b'test')
        (self.model/'config.json').write_text('{}', encoding='utf8')
        self.config = {'client_asr_model':'small','client_asr_model_dir':self.temp.name}

    def test_complete_local_model_does_not_use_network(self):
        with patch('faster_whisper.utils.download_model', return_value=str(self.model)) as download:
            self.assertEqual(loader.resolve_asr_model(self.config), str(self.model))
        self.assertEqual(download.call_count, 1)
        self.assertTrue(download.call_args.kwargs['local_files_only'])

    def test_missing_local_model_downloads_online(self):
        with patch('faster_whisper.utils.download_model', side_effect=FileNotFoundError('missing')) as download, patch('asr_model_download.download_small', return_value=str(self.model)) as online:
            self.assertEqual(loader.resolve_asr_model(self.config), str(self.model))
        self.assertEqual(download.call_count, 1)
        self.assertEqual(online.call_count, 1)

    def test_download_failure_is_explicit_without_model_fallback(self):
        with patch('faster_whisper.utils.download_model', side_effect=OSError('offline')) as download, patch('asr_model_download.download_small', side_effect=OSError('offline')):
            with self.assertRaisesRegex(RuntimeError, 'download failed'):
                loader.resolve_asr_model(self.config)
        self.assertTrue(all(c.args[0]=='small' for c in download.call_args_list))

    def test_missing_weight_is_not_accepted(self):
        (self.model/'model.bin').unlink()
        with self.assertRaisesRegex(ValueError, 'missing or empty'):
            loader.validate_model_files(self.model)


class StartupDiagnosticsTests(unittest.TestCase):
    def test_logs_before_ready_do_not_fail_startup(self):
        sys.path.insert(0, str(SRC))
        from redis_task_queue import PersistentAsrService
        service = Mock()
        service.process.stdout = io.StringIO('{"event":"asr_model_download_start"}\nDownloading...\n{"type":"ready","model":"small"}\n')
        ready = PersistentAsrService._wait_ready(service, 2)
        self.assertEqual(ready['model'], 'small')

    def test_fatal_download_failure_is_not_ready(self):
        sys.path.insert(0, str(SRC))
        from redis_task_queue import PersistentAsrService
        service = Mock()
        service.process.stdout = io.StringIO('{"event":"asr_model_download_start"}\n{"type":"fatal","error":"offline"}\n')
        with self.assertRaisesRegex(RuntimeError, 'offline'):
            PersistentAsrService._wait_ready(service, 2)


if __name__ == '__main__':
    unittest.main()
