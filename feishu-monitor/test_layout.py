import contextlib
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parent))
import monitor_paths

class LayoutTests(unittest.TestCase):
    def test_sibling_repository_and_chinese_deployment_without_parent_platform(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve()
            for label,english in monitor_paths.DEFAULTS.items():
                self.assertEqual(monitor_paths.platform_path(label,{},root),root/english)
                (root/label).mkdir()
                self.assertEqual(monitor_paths.platform_path(label,{},root),root/label)
                self.assertEqual(monitor_paths.platform_path(label,{'platform_directories':{label:english}},root),root/english)
            with self.assertRaises(ValueError):
                monitor_paths.platform_path('抖音',{'platform_directories':{'抖音':'../outside'}},root)

    def test_platforms_do_not_import_unified_monitor(self):
        package=Path(__file__).resolve().parents[1]
        for platform,file in [('小红书','run-worker.mjs'),('抖音','run-worker.mjs'),('视频号','redis_task_queue.py')]:
            source=(monitor_paths.platform_path(platform,package=package)/'common/src'/file).read_text(encoding='utf-8-sig')
            self.assertNotIn('feishu-monitor',source)

    def test_readonly_health_check_never_delivers_claims_or_modifies(self):
        spec=importlib.util.spec_from_file_location('layout_relay',Path(__file__).with_name('incident-relay.py'))
        relay=importlib.util.module_from_spec(spec);spec.loader.exec_module(relay)
        calls=[]
        class FakeRedis:
            def __init__(self,*args,**kwargs):pass
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def command(self,*args):
                calls.append(args[0])
                if args[0]=='TIME':return ['1','0']
                if args[0]=='HVALS':return []
                raise AssertionError(args)
        with patch.object(sys,'argv',['relay','--check']),patch.object(relay,'sources',return_value=[('小红书','ns','unused','hidden')]),patch.object(relay,'RedisConnection',FakeRedis),contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(relay.main(),0)
        self.assertTrue(json.loads(output.getvalue())['readOnly'])
        self.assertEqual(calls,['TIME','HVALS'])

    def test_monitor_entry_uses_sibling_path_helper_and_packaged_runtimes(self):
        root=Path(__file__).resolve().parent
        for name in ['run-once.ps1','run-incident-relay.ps1','remote-control.ps1']:
            source=(root/name).read_text(encoding='utf-8-sig')
            self.assertIn('Get-MonitorPlatformRoot',source)
            self.assertNotIn('..\\..\\$platformDirectory',source)
        self.assertIn('monitor-paths.mjs',(root/'database.mjs').read_text(encoding='utf-8'))

if __name__=='__main__':unittest.main()
