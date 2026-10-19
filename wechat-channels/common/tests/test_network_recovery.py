"""Offline regression tests: no production Redis, DB, browser, or task claims."""
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from contextlib import closing, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

COMMON = Path(__file__).parents[1]
sys.path.insert(0, str(COMMON / 'src'))
import channels_resilience as resilience
import redis_task_queue as scheduler
import volume_policy


class RedisNetworkRecoveryTests(unittest.TestCase):
    def test_delayed_clipboard_write_waits_without_clicking_again(self):
        import channels_pc_collector as collector
        url='https://weixin.qq.com/sph/FixtureOnly'
        with patch.object(collector,'get_clipboard',side_effect=['',url]) as read, redirect_stdout(io.StringIO()):
            self.assertEqual(collector.wait_for_channels_clipboard(.5),url)
        self.assertEqual(read.call_count,2)

    def test_clipboard_content_and_access_error_never_leak_to_logs(self):
        import channels_pc_collector as collector
        for value in ('secret-user-clipboard',OSError('secret-user-clipboard')):
            kwargs={'side_effect':value} if isinstance(value,Exception) else {'return_value':value}
            with self.subTest(value=type(value).__name__),patch.object(collector,'get_clipboard',**kwargs):
                with self.assertRaises(RuntimeError) as caught:collector.wait_for_channels_clipboard(0)
                self.assertNotIn('secret-user-clipboard',str(caught.exception))

    def test_transport_timeout_is_sanitized_and_has_bounded_timeout(self):
        with patch.object(scheduler, 'redis_command', side_effect=TimeoutError('secret-password')) as call:
            with self.assertRaises(resilience.RedisCheckpointUnavailable) as caught:
                resilience.RedisVideoCheckpointStore._command('redis://fixture', 'secret-password', 'PING')
        self.assertNotIn('secret-password', str(caught.exception))
        self.assertEqual(call.call_args.kwargs['timeout'], 5)

    def test_unreachable_host_is_an_infrastructure_error(self):
        with patch.object(scheduler, 'redis_command', side_effect=OSError(10065, 'unreachable')):
            with self.assertRaises(resilience.RedisCheckpointUnavailable):
                resilience.RedisVideoCheckpointStore._command('redis://fixture', None, 'PING')

    def test_closed_connection_is_not_a_content_failure(self):
        with patch.object(scheduler, 'redis_command', side_effect=scheduler.RedisError('Redis closed the connection')):
            with self.assertRaises(resilience.RedisCheckpointUnavailable):
                resilience.RedisVideoCheckpointStore._command('redis://fixture', None, 'PING')

    def test_auth_and_identity_errors_are_not_hidden_as_network_errors(self):
        for error in ('WRONGPASS', 'CHECKPOINT_IDENTITY_CONFLICT'):
            with self.subTest(error=error), patch.object(scheduler, 'redis_command', side_effect=scheduler.RedisError(error)):
                with self.assertRaises(scheduler.RedisError):
                    resilience.RedisVideoCheckpointStore._command('redis://fixture', None, 'PING')

    def test_real_sqlite_checkpoint_is_committed_before_remote_failure(self):
        import channels_pc_collector as collector
        with tempfile.TemporaryDirectory() as folder:
            filename = Path(folder) / 'checkpoint.sqlite'
            remote = resilience.RedisVideoCheckpointStore()
            remote.enabled = True
            with closing(collector.init_state(filename)) as db:
                with patch.object(scheduler, 'redis_command', side_effect=TimeoutError()):
                    with self.assertRaises(resilience.RedisCheckpointUnavailable):
                        collector.upsert_video_checkpoint(db, keyword='fixture', project='fixture',
                            fingerprint='fp', status='retry_pending', retry_count=1,
                            last_error='original-detail-error', remote_store=remote)
            with closing(collector.init_state(filename)) as db:
                restored = collector.load_video_checkpoints(db, 'fixture')['fp']
            self.assertEqual(restored['status'], 'retry_pending')
            self.assertEqual(restored['retry_count'], 1)
            self.assertEqual(restored['last_error'], 'original-detail-error')

    def test_operational_cli_imports_in_real_embedded_python(self):
        runtime = COMMON / 'runtime/python/python.exe'
        if not runtime.exists():
            self.skipTest('Embedded Windows runtime not installed')
        env = dict(os.environ)
        env.pop('REDIS_URL', None)
        env.pop('REDIS_PASSWORD', None)
        result = subprocess.run([str(runtime), str(COMMON / 'src/operational_gate.py'), '--check'],
            env=env, capture_output=True, timeout=15, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        self.assertEqual(result.returncode, 1)
        self.assertIn(b'KeyError', result.stderr)
        self.assertNotIn(b'ModuleNotFoundError', result.stderr)

    def test_volume_outage_never_finalizes_or_reads_followup_incident(self):
        for recollection in (False, True):
            with self.subTest(recollection=recollection), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                args = SimpleNamespace(worker_root=root, prefix='fixture', stream='fixture:tasks',
                    group='g', once=False, consumer='fixture')
                runtime = MagicMock()
                item = {'task_id':'original','keyword':'fixture'}
                if recollection:
                    item['_recollectPolicy'] = 'fixture'
                runtime.claim_next.return_value = ('1-0', item)
                args.volume_runtime = runtime
                api = MagicMock()
                api.run_task.return_value = 75
                control = MagicMock()
                control.poll.return_value = False
                operations = MagicMock()
                operations.wait.return_value = True
                operations.read.return_value = {'lastSeenAt':0}
                with patch.object(volume_policy, 'preflight_local_environment'), \
                     patch.object(volume_policy, 'OperationalGate', return_value=operations), \
                     patch.object(volume_policy.signal, 'signal'), redirect_stdout(io.StringIO()):
                    result = volume_policy.run_volume_worker(api, args, threading.Event(), control)
                self.assertEqual(result, 75)
                runtime.finish.assert_not_called()
                runtime.recollection.finish.assert_not_called()
                self.assertEqual(operations.read.call_count, 1)
                self.assertEqual(runtime.claim_next.call_count, 1)
                api.PersistentAsrService.return_value.stop.assert_called_once()
                self.assertEqual(api.write_json.call_args.args[1]['status'], 'infrastructure_paused')

    def test_standard_scheduler_outage_never_acks_or_finalizes(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            args = SimpleNamespace(worker_root=root, redis_url='redis://fixture', redis_password=None,
                prefix='fixture',stream='fixture:tasks',retry_stream='fixture:retry',group='g',retry_group='r',
                seeded_key='fixture:seeded', status_key='fixture:status',consumer='fixture',common=COMMON,
                queue=root/'queue.json',once=False,block_seconds=1,reclaim_idle_seconds=300)
            args.queue.write_text('{"tasks": []}', encoding='utf-8')
            control = MagicMock(); control.poll.return_value = False
            message = ('1-0', {'task_id':'original','topic':'t','keyword':'fixture','queue':{'tasks':[]}})
            with patch.object(scheduler, 'ensure_group'), patch.object(scheduler, 'seed_tasks', return_value=0), \
                 patch.object(volume_policy, 'open_runtime', return_value=None), \
                 patch.object(scheduler,'publish_remote_log'), patch('retry_round.claim_round',return_value=(False,None,None,None)), \
                 patch.object(scheduler,'claim_primary_message',return_value=(message,False)) as claim, \
                 patch.object(scheduler,'run_task',return_value=75), patch.object(scheduler,'redis_command') as command, \
                 patch.object(scheduler,'checkpoint_completion_guard') as guard, \
                 patch.object(scheduler,'update_remote_status') as finalizer, redirect_stdout(io.StringIO()):
                result = scheduler._run_worker(args,threading.Event(),control)
            self.assertEqual(result,75)
            self.assertEqual(claim.call_count,1)
            guard.assert_not_called();finalizer.assert_not_called()
            self.assertFalse(any(call.args[2:3] == ('XACK',) for call in command.call_args_list))
            self.assertEqual(json.loads((root/'.state/redis_worker_status.json').read_text())['status'],'infrastructure_paused')

    def test_lost_lease_overrides_nonzero_content_exit(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);state=root/'.state/redis_worker_status.json';state.parent.mkdir()
            args=SimpleNamespace(worker_root=root,redis_url='redis://fixture',redis_password=None,
                run_id='fixture',run_generation='fixture',common=COMMON,stream='fixture:tasks',group='g',
                consumer='fixture',heartbeat_seconds=30,heartbeat_failure_limit=3,once=False)
            item={'task_id':'original','keyword':'fixture','topic':'fixture','queue':{'tasks':[]}}
            heartbeat=MagicMock();heartbeat.lease_lost.is_set.return_value=True
            process=MagicMock();process.poll.return_value=3;process.returncode=3
            with patch.object(scheduler,'LeaseHeartbeat',return_value=heartbeat), \
                 patch.object(scheduler.subprocess,'Popen',return_value=process), \
                 patch.object(scheduler,'publish_remote_log'),patch.object(scheduler,'forward_child_output'), \
                 patch.object(scheduler,'publish_child_output'),patch.object(scheduler,'stop_child_log_publisher'):
                self.assertEqual(scheduler.run_task(args,'1-0',item,state),75)
            heartbeat.stop.assert_called_once()

    def test_interrupted_claim_cannot_prove_retry_exhaustion(self):
        self.assertIn("previous.status~='retry_pending' or previous.verifiedContentAttempt~=true",volume_policy.TRANSITION)
        self.assertIn('verifiedContentAttempt=true',volume_policy.TRANSITION)


@unittest.skipUnless(os.name == 'nt' and shutil.which('powershell.exe'), 'Windows PowerShell fixture')
class PowerShellRecoveryTests(unittest.TestCase):
    def test_real_worker_exit75_salvages_and_never_starts_second_keyword(self):
        runtime = COMMON / 'runtime/python/python.exe'
        node = COMMON / 'runtime/node/node.exe'
        if not runtime.is_file() or not node.is_file():
            self.skipTest('Portable runtimes required')
        for failure in ('checkpoint', 'operational', 'export'):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as folder:
                root=Path(folder); common=root/'common'; src=common/'src'; src.mkdir(parents=True)
                worker=root/'worker-02';worker.mkdir()
                for name in ('run-worker.ps1','worker-recovery.ps1'):
                    shutil.copy2(COMMON/name,common/name)
                (common/'check-env.ps1').write_text("'{\"ok\":true}'",encoding='ascii')
                (common/'collector_config.json').write_text(json.dumps({'jitter_enabled':False,
                    'keyword_retry_attempts':1}),encoding='ascii')
                queue={'cutoff':'2026-01-01','tasks':[{'id':'fixture','name':'fixture',
                    'keywordsFile':'keywords.txt','keywordAllowList':['first','second'],'collectComments':False}]}
                (root/'keywords.txt').write_text('first\nsecond',encoding='ascii')
                (worker/'task-queue.json').write_text(json.dumps(queue),encoding='ascii')
                # All executable children are local fixtures. No network or UI.
                (src/'channels_pc_collector.py').write_text('''import sys,pathlib,os
a=sys.argv
def value(k): return a[a.index(k)+1]
if a[1]=='export-ods':
 if os.environ['FIXTURE_FAILURE']=='export': sys.exit(9)
 pathlib.Path(value('--output-dir'),'ods_social_media_post_channels.jsonl').write_text('{}')
 sys.exit(0)
pathlib.Path(value('--state-db')).write_bytes(b'durable-fixture-checkpoint')
sys.exit(4 if os.environ['FIXTURE_FAILURE']=='operational' else 75)
''',encoding='ascii')
                (src/'operational_gate.py').write_text('import sys;sys.exit(75)',encoding='ascii')
                (src/'channels_browser_enricher.mjs').write_text("import fs from 'node:fs';fs.writeFileSync(process.argv[3],'{}');",encoding='ascii')
                (src/'channels_ods_postprocess.mjs').write_text("import fs from 'node:fs';fs.writeFileSync(process.argv[4],'{}');",encoding='ascii')
                env={**os.environ,'WECHAT_WORKER_ROOT':str(worker),'WECHAT_PYTHON':str(runtime),
                    'WECHAT_NODE':str(node),'MYSQL_ENABLED':'0','WECHAT_REDIS_STATE_SCOPE':'fixture',
                    'REDIS_URL':'redis://unused.invalid:1','FIXTURE_FAILURE':failure,
                    'SOCIAL_VOLUME_ENABLED':'1'}
                env.pop('WECHAT_QUEUE_FILE',None)
                result=subprocess.run(['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass',
                    '-File',str(common/'run-worker.ps1')],env=env,capture_output=True,timeout=25,
                    creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                self.assertEqual(result.returncode,75,result.stderr.decode(errors='replace'))
                report=json.loads((worker/'.state/worker_status.json').read_text(encoding='utf-8-sig'))
                self.assertTrue(report['infrastructureBlocked'])
                rows=[k for t in report['tasks'] for k in t['keywords']]
                self.assertEqual([k['keyword'] for k in rows],['first'])
                self.assertEqual(rows[0]['status'],'failed')
                self.assertFalse(rows[0]['salvage']['importConfirmed'])
                if failure!='export':self.assertTrue(rows[0]['salvage']['remoteEnrichmentSkipped'])
                self.assertEqual(rows[0]['salvage']['exportConfirmed'],failure!='export')
                self.assertNotIn(b'committed rows were exported/imported',result.stdout)
                self.assertEqual((worker/'.state/redis-runs/fixture/fixture.sqlite').read_bytes(),b'durable-fixture-checkpoint')

    def run_fixture(self, mode):
        script = r'''
$ErrorActionPreference='Stop'
. $env:RECOVERY_HELPER
$out=$env:RECOVERY_ROOT
$state=Join-Path $out 'checkpoint.sqlite'
[IO.File]::WriteAllText($state,'unchanged-sqlite-fixture')
[IO.File]::WriteAllText((Join-Path $out 'mysql_import_status.json'),'{"status":"success","old":true}')
function FixturePython {
  if($env:RECOVERY_MODE -eq 'exportfail'){$global:LASTEXITCODE=5;return}
  [IO.File]::WriteAllText((Join-Path $env:RECOVERY_ROOT 'ods_social_media_post_channels.jsonl'),'{}')
  $global:LASTEXITCODE=0
}
function FixtureNode {
  $global:LASTEXITCODE=0
  if($args[0] -eq 'enricher'){
    if($env:RECOVERY_MODE -eq 'offline'){throw 'Must not launch remote enrichment during infrastructure recovery'}
    if($env:RECOVERY_MODE -eq 'enrichfail'){$global:LASTEXITCODE=5}
  } elseif($args[0] -eq 'post'){
    if($env:RECOVERY_MODE -eq 'postfail'){$global:LASTEXITCODE=5;return}
    [IO.File]::WriteAllText((Join-Path $env:RECOVERY_ROOT 'ods_social_media_post_channels_final.jsonl'),'{}')
  } elseif($args[0] -eq 'importer'){
    if($env:RECOVERY_MODE -eq 'importfail'){$global:LASTEXITCODE=5;return}
    if($env:RECOVERY_MODE -eq 'stalestatus'){return}
    $i=[array]::IndexOf($args,'--status')
    $value=if($env:RECOVERY_MODE -eq 'failedstatus'){'{"status":"failed"}'}else{'{"status":"success","posts":1}'}
    [IO.File]::WriteAllText($args[$i+1],$value)
  }
}
$result=Invoke-KeywordCheckpointSalvage -Python FixturePython -Node FixtureNode -Collector unused -Enricher enricher -Postprocessor post -Importer importer -OutputDir $out -StateDb $state -Keyword fixture -CollectComments $false -DatabaseEnabled ($env:RECOVERY_MODE -ne 'nodb') -OfflineOnly ($env:RECOVERY_MODE -eq 'offline')
$message=Get-KeywordRecoveryMessage $result
@{result=$result;message=$message;checkpoint=[IO.File]::ReadAllText($state)}|ConvertTo-Json -Depth 15 -Compress
'''
        with tempfile.TemporaryDirectory() as folder:
            env = {**os.environ,'RECOVERY_ROOT':folder,'RECOVERY_MODE':mode,
                'RECOVERY_HELPER':str(COMMON/'worker-recovery.ps1')}
            result = subprocess.run(['powershell.exe','-NoProfile','-Command',script],env=env,
                capture_output=True,text=True,timeout=25,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            self.assertEqual(result.returncode,0,result.stderr)
            report=json.loads(result.stdout)
            self.assertEqual(report['checkpoint'],'unchanged-sqlite-fixture')
            alias=json.loads((Path(folder)/'mysql_import_status.json').read_text(encoding='utf-8-sig'))
            return report, alias

    def test_verified_success(self):
        report,alias=self.run_fixture('success')
        self.assertTrue(report['result']['success'])
        self.assertTrue(report['result']['importConfirmed'])
        self.assertIn('import was confirmed',report['message'])
        self.assertEqual(alias['status'],'success')

    def test_infrastructure_recovery_never_launches_browser_enrichment(self):
        report,alias=self.run_fixture('offline')
        self.assertTrue(report['result']['success'])
        self.assertTrue(report['result']['remoteEnrichmentSkipped'])
        self.assertTrue(report['result']['importConfirmed'])
        self.assertEqual(alias['status'],'success')

    def test_each_failure_preserves_checkpoint_and_never_claims_import(self):
        for mode in ('exportfail','enrichfail','postfail','importfail','stalestatus','failedstatus'):
            with self.subTest(mode=mode):
                report,alias=self.run_fixture(mode)
                self.assertFalse(report['result']['success'])
                self.assertFalse(report['result']['importConfirmed'])
                self.assertIn('NOT confirmed',report['message'])
                self.assertEqual(alias['status'],'failed')
                self.assertEqual(report['result']['exportConfirmed'],mode!='exportfail')

    def test_database_disabled_never_claims_import(self):
        report,_=self.run_fixture('nodb')
        self.assertTrue(report['result']['success'])
        self.assertTrue(report['result']['exportConfirmed'])
        self.assertFalse(report['result']['importConfirmed'])
        self.assertEqual(report['result']['mysql']['status'],'disabled')


if __name__ == '__main__':
    unittest.main()
