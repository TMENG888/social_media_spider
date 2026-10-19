"""Updater tests exclusively use temporary target copies, never production."""
import json
import ctypes
from ctypes import wintypes
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

COMMON=Path(__file__).parents[1]
BUNDLE=COMMON.parent/'修复包-Redis断网收尾-20261017'


@unittest.skipUnless(os.name=='nt' and shutil.which('powershell.exe') and BUNDLE.is_dir(),'Local Windows repair bundle')
class BundleTests(unittest.TestCase):
    def fixture(self,root):
        target=root/'video';target.mkdir()
        manifest=json.loads((BUNDLE/'manifest.json').read_text(encoding='utf-8-sig'))
        originals={}
        for entry in manifest['files']:
            path=target/entry['path']
            if path.name=='worker-recovery.ps1':continue
            path.parent.mkdir(parents=True,exist_ok=True)
            content=('original-fixture:'+entry['path']).encode()
            path.write_bytes(content);originals[entry['path']]=content
        return target,manifest,originals

    def run_updater(self,target,bundle=BUNDLE,check=False):
        command=['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(bundle/'apply-repair.ps1'),
            '-TargetRoot',str(target),'-PythonExecutable',str(COMMON/'runtime/python/python.exe')]
        if check:command+=['-CheckOnly']
        return subprocess.run(command,capture_output=True,timeout=25,
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))

    def test_check_only_does_not_change_any_target_file(self):
        with tempfile.TemporaryDirectory() as folder:
            target,_,originals=self.fixture(Path(folder))
            result=self.run_updater(target,check=True)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            for path,content in originals.items():self.assertEqual((target/path).read_bytes(),content)
            self.assertFalse((target/'maintenance-backups').exists())
            self.assertFalse((target/'common/worker-recovery.ps1').exists())

    def test_apply_backs_up_exact_originals_and_installs_all_files(self):
        with tempfile.TemporaryDirectory() as folder:
            target,manifest,originals=self.fixture(Path(folder))
            result=self.run_updater(target)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            self.assertIn(b'APPLIED OK',result.stdout)
            backups=list((target/'maintenance-backups').iterdir());self.assertEqual(len(backups),1)
            for path,content in originals.items():self.assertEqual((backups[0]/path).read_bytes(),content)
            for entry in manifest['files']:
                self.assertEqual((target/entry['path']).read_bytes(),(BUNDLE/'payload'/entry['path']).read_bytes())
            self.assertFalse((target/'.state').exists())

    def test_damaged_payload_rejected_before_any_target_change(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);target,_,originals=self.fixture(root)
            broken=root/'broken-bundle';shutil.copytree(BUNDLE,broken)
            (broken/'payload/common/worker-recovery.ps1').write_text('# changed fixture',encoding='ascii')
            result=self.run_updater(target,broken)
            self.assertNotEqual(result.returncode,0)
            self.assertIn(b'checksum mismatch',result.stdout)
            for path,content in originals.items():self.assertEqual((target/path).read_bytes(),content)
            self.assertFalse((target/'maintenance-backups').exists())

    def test_running_fixture_process_blocks_update_without_stopping_it(self):
        with tempfile.TemporaryDirectory() as folder:
            target,_,originals=self.fixture(Path(folder))
            sleeper=subprocess.Popen(['powershell.exe','-NoProfile','-Command',
                'Start-Sleep -Seconds 25 # '+str(target/'common/run-worker.ps1')],
                stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            try:
                result=self.run_updater(target)
                self.assertNotEqual(result.returncode,0)
                self.assertIn(b'processes are still running',result.stdout)
                self.assertIsNone(sleeper.poll())
                for path,content in originals.items():self.assertEqual((target/path).read_bytes(),content)
                self.assertFalse((target/'maintenance-backups').exists())
            finally:
                # This exact PID is the temporary sleeper created above, not a collector.
                sleeper.terminate();sleeper.wait(timeout=10)

    def test_mid_update_failure_rolls_back_originals_and_new_helper(self):
        with tempfile.TemporaryDirectory() as folder:
            target,_,originals=self.fixture(Path(folder))
            kernel=ctypes.WinDLL('kernel32',use_last_error=True)
            kernel.CreateFileW.argtypes=[wintypes.LPCWSTR,wintypes.DWORD,wintypes.DWORD,
                ctypes.c_void_p,wintypes.DWORD,wintypes.DWORD,wintypes.HANDLE]
            kernel.CreateFileW.restype=wintypes.HANDLE
            kernel.CloseHandle.argtypes=[wintypes.HANDLE]
            # Allow backup reads but deny replacement of the third file.
            handle=kernel.CreateFileW(str(target/'common/src/operational_gate.py'),
                0x80000000,1,None,3,0x80,None)
            self.assertNotEqual(handle,ctypes.c_void_p(-1).value)
            try:
                result=self.run_updater(target)
            finally:kernel.CloseHandle(handle)
            self.assertNotEqual(result.returncode,0)
            self.assertIn(b'Changed files rolled back',result.stdout)
            for path,content in originals.items():self.assertEqual((target/path).read_bytes(),content)
            self.assertFalse((target/'common/worker-recovery.ps1').exists())
            self.assertTrue((target/'maintenance-backups').exists())


if __name__=='__main__':unittest.main()
