import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

COMMON = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(COMMON/'src'))
import database_diagnostics as diagnostic
import volume_policy as volume


class DatabaseDiagnosticsTests(unittest.TestCase):
    def test_no_worker_context_never_writes_or_publishes(self):
        self.assertIsNone(diagnostic.observe(COMMON, {'operation':'task'}, 'ECONNREFUSED', env={}))

    def test_safe_target_and_error_never_include_credentials(self):
        self.assertEqual(diagnostic.safe_code('mysql://secret@host'), 'VOLUME_READBACK_FAILED')
        target=diagnostic.target(COMMON, {'MYSQL_HOST':'mysql://secret@host', 'MYSQL_DATABASE':'user:secret@db', 'MYSQL_PASSWORD':'secret'})
        self.assertNotIn('secret', json.dumps(target))
        self.assertEqual(target['host'], 'unknown')

    def test_fault_dedup_offline_replay_and_true_query_recovery(self):
        with tempfile.TemporaryDirectory() as folder, contextlib.redirect_stdout(io.StringIO()) as output:
            worker=Path(folder)/'worker-01'
            env={'WECHAT_WORKER_ROOT':str(worker),'MYSQL_HOST':'127.0.0.1',
                 'MYSQL_USER':'SECRET-USER','MYSQL_PASSWORD':'SECRET-PASSWORD'}
            request={'operation':'task','taskId':'original'}
            first=diagnostic.observe(COMMON,request,'ECONNREFUSED','connect',env=env)
            self.assertFalse(first['monitorQueued'])
            diagnostic.observe(COMMON,request,'ECONNREFUSED','connect',env=env)
            state=worker/'.state'
            self.assertEqual(len(json.loads((state/'database-monitor-outbox.json').read_text(encoding='utf-8'))),1)
            # Shared policy validation succeeds without SQL: not a recovery.
            self.assertIsNone(diagnostic.observe(COMMON,{'operation':'validate'},env=env))
            self.assertEqual(json.loads((state/'database-readback-status.json').read_text(encoding='utf-8'))['status'],'active')
            calls=[]
            env.update(REDIS_URL='redis://fixture',REDIS_RUN_ID='fixture-run')
            result=diagnostic.observe(COMMON,request,env=env,command=lambda *args:calls.append(args) or 1)
            self.assertTrue(result['monitorQueued'])
            self.assertEqual([call[5] for call in calls],['record','resolve'])
            for call in calls:
                self.assertEqual(call[0],'EVAL')
                self.assertEqual(call[3],'wechat:channels:fixture-run:monitor:database-incidents')
                self.assertEqual(call[4],'wechat:channels:fixture-run:monitor:outbox')
            diagnostic.observe(COMMON,request,env=env,command=lambda *args:self.fail('duplicate recovery'))
            self.assertEqual(len((state/'database-readback-events.jsonl').read_text(encoding='utf-8').splitlines()),2)
            self.assertEqual(json.loads((state/'database-monitor-outbox.json').read_text(encoding='utf-8')),[])
            all_text=output.getvalue()+''.join(f.read_text(encoding='utf-8') for f in state.iterdir())
            self.assertNotIn('SECRET-',all_text)

    def test_bridge_preserves_safe_codes_and_never_prints_raw_stderr(self):
        process=SimpleNamespace(returncode=1,stdout='',stderr='SECRET-URL\n'+json.dumps({'errorCode':'ER_ACCESS_DENIED_ERROR','stage':'connect'}))
        with patch.object(volume.shutil,'which',return_value='node'), patch.object(volume.subprocess,'run',return_value=process), patch.object(volume,'observe_database') as observed:
            with self.assertRaisesRegex(RuntimeError,'VOLUME_DATABASE_READBACK_FAILED:ER_ACCESS_DENIED_ERROR'):
                volume.bridge(COMMON,{'operation':'task'})
            observed.assert_called_once_with(COMMON,{'operation':'task'},'ER_ACCESS_DENIED_ERROR','connect')

    def test_bridge_runtime_timeout_and_invalid_response_fail_closed(self):
        for process,code,stage in [
            (SimpleNamespace(returncode=1,stdout='',stderr='ERR_MODULE_NOT_FOUND SECRET'),'NODE_DEPENDENCY_MISSING','runtime'),
            (SimpleNamespace(returncode=0,stdout='not-json SECRET',stderr=''),'VOLUME_READBACK_INVALID_RESPONSE','response'),
            (SimpleNamespace(returncode=1,stdout='',stderr=json.dumps({'errorCode':'SECRET','stage':'unknown'})),'VOLUME_READBACK_FAILED','unknown')]:
            with patch.object(volume.shutil,'which',return_value='node'),patch.object(volume.subprocess,'run',return_value=process),patch.object(volume,'observe_database') as observed:
                with self.assertRaisesRegex(RuntimeError,'VOLUME_DATABASE_READBACK_FAILED:'+code):
                    volume.bridge(COMMON,{'operation':'task'})
                observed.assert_called_once_with(COMMON,{'operation':'task'},code,stage)
        with patch.object(volume.shutil,'which',return_value='node'),patch.object(volume.subprocess,'run',side_effect=subprocess.TimeoutExpired('SECRET',180)),patch.object(volume,'observe_database') as observed:
            with self.assertRaisesRegex(RuntimeError,'VOLUME_DATABASE_READBACK_TIMEOUT'):
                volume.bridge(COMMON,{'operation':'task'})
            self.assertEqual(observed.call_args.args[2],'VOLUME_DATABASE_READBACK_TIMEOUT')

    def test_monitor_failure_cannot_replace_primary_error_or_fake_recovery(self):
        failed=SimpleNamespace(returncode=1,stdout='',stderr=json.dumps({'errorCode':'ECONNREFUSED','stage':'connect'}))
        with patch.object(volume.shutil,'which',return_value='node'),patch.object(volume.subprocess,'run',return_value=failed),patch.object(volume,'observe_database',side_effect=OSError('SECRET')),contextlib.redirect_stdout(io.StringIO()) as output:
            with self.assertRaisesRegex(RuntimeError,'ECONNREFUSED'):
                volume.bridge(COMMON,{'operation':'task'})
            self.assertNotIn('SECRET',output.getvalue())
        for operation,result,expected in [('validate',{'ok':True},False),('task',{'dbReadbackVerified':True},True),('task',{'ok':True},False)]:
            with patch.object(volume.shutil,'which',return_value='node'),patch.object(volume.subprocess,'run',return_value=SimpleNamespace(returncode=0,stdout=json.dumps(result))),patch.object(volume,'observe_database') as observed:
                volume.bridge(COMMON,{'operation':operation})
                self.assertEqual(observed.called,expected)

    def test_corrupt_local_outbox_is_preserved_not_silently_dropped(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)/'.state';root.mkdir()
            file=root/'database-monitor-outbox.json';file.write_text('broken',encoding='utf-8')
            with self.assertRaises(ValueError):
                diagnostic.observe(COMMON,{'operation':'task'},'ECONNREFUSED',env={'WECHAT_WORKER_ROOT':folder})
            self.assertEqual(file.read_text(encoding='utf-8'),'broken')


@unittest.skipUnless(os.environ.get('DATABASE_MONITOR_LIVE_TEST')=='1','isolated monitoring-key fixture opt-in')
class DatabaseIncidentLuaTests(unittest.TestCase):
    def test_real_redis_dedup_resolution_and_no_task_access(self):
        from redis_task_queue import redis_command
        url=os.environ['DATABASE_MONITOR_REDIS_URL'];password=os.environ.get('DATABASE_MONITOR_REDIS_PASSWORD')
        prefix='wechat:channels:monitor-diagnostics-fixture:monitor:'+uuid.uuid4().hex
        states,outbox=prefix+':state',prefix+':outbox'
        script=(COMMON/'src/database-incident.lua').read_text(encoding='utf-8')
        request={'kind':'database','status':'active','signature':'fixture-signature','errorCode':'ECONNREFUSED'}
        call=lambda *args:redis_command(url,password,*args)
        try:
            self.assertEqual(call('EVAL',script,2,states,outbox,'record','fixture',json.dumps(request)),1)
            self.assertEqual(call('EVAL',script,2,states,outbox,'record','fixture',json.dumps(request)),0)
            self.assertEqual(call('HLEN',outbox),1)
            request['databaseReadbackVerified']=True
            self.assertEqual(call('EVAL',script,2,states,outbox,'resolve','fixture',json.dumps(request)),1)
            self.assertEqual(call('EVAL',script,2,states,outbox,'resolve','fixture',json.dumps(request)),0)
            self.assertEqual(call('HLEN',outbox),2)
        finally:
            # Only these exact, freshly-created monitor fixture keys.
            call('DEL',states,outbox)


@unittest.skipUnless(os.environ.get('DATABASE_MONITOR_SQL_LIVE_TEST')=='1','read-only MySQL fixture opt-in')
class DatabaseReadbackLiveTests(unittest.TestCase):
    def test_real_query_fault_and_recovery_are_recorded_without_task_or_alert_writes(self):
        deployed=Path(os.environ['DATABASE_MONITOR_COMMON'])
        snapshot=json.loads((deployed.parent/'worker-01/.state/volume-acceptance-snapshot.json').read_text(encoding='utf-8-sig'))
        defaults=json.loads((deployed/'src/mysql-defaults.json').read_text(encoding='utf-8-sig'))
        request={'operation':'task','snapshot':snapshot,'taskId':snapshot['entries'][0]['taskId']}
        with tempfile.TemporaryDirectory() as folder, contextlib.redirect_stdout(io.StringIO()) as output:
            changes={'WECHAT_WORKER_ROOT':str(Path(folder)/'worker-fixture'),'MYSQL_HOST':'127.0.0.1','REDIS_URL':''}
            with patch.dict(os.environ,changes):
                with self.assertRaisesRegex(RuntimeError,'ECONNREFUSED'):
                    volume.bridge(deployed,request)
                os.environ['MYSQL_HOST']=defaults['host']
                result=volume.bridge(deployed,request)
            self.assertTrue(result['dbReadbackVerified'])
            state=Path(changes['WECHAT_WORKER_ROOT'])/'.state'
            events=[json.loads(line) for line in (state/'database-readback-events.jsonl').read_text(encoding='utf-8').splitlines()]
            self.assertEqual([e['status'] for e in events],['active','resolved'])
            self.assertEqual(events[0]['errorCode'],'ECONNREFUSED')
            self.assertEqual(events[0]['stage'],'connect')
            self.assertTrue(all(e['taskDispositionChanged'] is False for e in events))
            self.assertEqual(len(json.loads((state/'database-monitor-outbox.json').read_text(encoding='utf-8'))),2)
            self.assertNotIn(os.environ['MYSQL_PASSWORD'],output.getvalue())


if __name__=='__main__':unittest.main()
