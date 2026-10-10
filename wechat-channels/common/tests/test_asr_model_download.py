import sys,io,hashlib,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
import asr_model_download as d

class DownloadTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.data=b'validated-model-test'
        self.files={'model.bin':(len(self.data),hashlib.sha256(self.data).hexdigest())}

    def test_failed_source_falls_back_and_publishes_verified_file(self):
        with patch.object(d,'FILES',self.files), patch.object(d,'urlopen',side_effect=[OSError('offline'),io.BytesIO(self.data)]) as network:
            folder=d.download_small(self.tmp.name,{'client_asr_download_endpoints':['https://source','https://mirror']})
            self.assertEqual((Path(folder)/'model.bin').read_bytes(),self.data)
            self.assertEqual(network.call_count,2)
            self.assertFalse((Path(folder)/'model.bin.part').exists())
            self.assertEqual(d.download_small(self.tmp.name,{}),folder)
            self.assertEqual(network.call_count,2)

    def test_corrupt_download_is_not_accepted_and_failure_cools_down(self):
        with patch.object(d,'FILES',self.files), patch.object(d,'urlopen',return_value=io.BytesIO(b'corrupt')) as network:
            with self.assertRaisesRegex(RuntimeError,'mismatch'):
                d.download_small(self.tmp.name,{'client_asr_download_endpoints':['https://source']})
            with self.assertRaisesRegex(RuntimeError,'cooling down'):
                d.download_small(self.tmp.name,{})
            self.assertEqual(network.call_count,1)
            self.assertIsNone(d.portable_small(self.tmp.name))

    def test_git_blob_checksum_is_validated(self):
        path=Path(self.tmp.name)/'config.json';path.write_bytes(self.data)
        digest=hashlib.sha1(f'blob {len(self.data)}\0'.encode()+self.data).hexdigest()
        with patch.object(d,'FILES',{'config.json':(len(self.data),digest)}):
            self.assertTrue(d.valid_file(path,'config.json'))
            path.write_bytes(b'x'*len(self.data))
            self.assertFalse(d.valid_file(path,'config.json'))

    def test_launcher_checks_model_before_scheduler(self):
        source=(Path(__file__).resolve().parents[1]/'run-redis-worker.ps1').read_text(encoding='utf-8-sig')
        self.assertLess(source.index('asr_model_preflight.py'),source.index('& $Python @arguments'))
