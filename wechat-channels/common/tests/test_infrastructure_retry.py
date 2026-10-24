"""Fault injection only: no production Redis/MySQL, UI or task mutations."""
import contextlib
import io
import json
import sys
import tempfile
import unittest
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch

COMMON=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(COMMON/'src'))
import infrastructure_retry
import channels_resilience as resilience
import redis_task_queue as scheduler
import volume_policy


class InfrastructureRetryTests(unittest.TestCase):
    def test_bridge_forwards_only_safe_retry_progress_and_verified_final_readback(self):
        stderr='SECRET raw driver error\n'+json.dumps({'event':'infrastructure_retry_wait','operation':'database_readback',
            'errorCode':'ENOTFOUND','attempt':1,'nextAttempt':2,'waitSeconds':5,'password':'SECRET'})
        process=SimpleNamespace(returncode=0,stdout=json.dumps({'dbReadbackVerified':True,'posts':29}),stderr=stderr)
        with patch.object(volume_policy.shutil,'which',return_value='node'), \
             patch.object(volume_policy.subprocess,'run',return_value=process), \
             patch.object(volume_policy,'observe_database') as observed, contextlib.redirect_stdout(io.StringIO()) as output:
            result=volume_policy.bridge(COMMON,{'operation':'task'})
        self.assertEqual(result['posts'],29);self.assertNotIn('SECRET',output.getvalue())
        self.assertIn('infrastructure_retry_wait',output.getvalue());observed.assert_called_once_with(COMMON,{'operation':'task'},None,'unknown')

    def test_checkpoint_recovers_or_fuses_after_three_safe_attempts(self):
        for failures in (1,2,3):
            calls=[];waits=[];logs=[]
            def run():
                calls.append(1)
                if len(calls)<=failures: raise TimeoutError('SECRET-PASSWORD')
                return 'ok'
            if failures==3:
                with self.assertRaises(TimeoutError):
                    infrastructure_retry.retry_checkpoint(run,pause=waits.append,log=logs.append)
                self.assertEqual(logs[-1]['event'],'redis_checkpoint_circuit_open')
            else:
                self.assertEqual(infrastructure_retry.retry_checkpoint(run,pause=waits.append,log=logs.append),'ok')
                self.assertEqual(logs[-1]['event'],'redis_checkpoint_retry_recovered')
            self.assertEqual(len(calls),min(failures+1,3))
            self.assertNotIn('SECRET',json.dumps(logs))
            self.assertEqual(waits,[1,2][:min(failures,2)])

    def test_transport_reconnect_and_auth_fail_fast_without_task_commands(self):
        with patch.object(scheduler,'redis_command',side_effect=[TimeoutError(),'checkpoint']), \
             patch.object(infrastructure_retry.time,'sleep') as wait, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(resilience.RedisVideoCheckpointStore._command('redis://fixture',None,'HGET','fixture','id'),'checkpoint')
            wait.assert_called_once_with(1)
        for code in ('WRONGPASS','NOPERM','CHECKPOINT_IDENTITY_CONFLICT'):
            with patch.object(scheduler,'redis_command',side_effect=scheduler.RedisError(code)) as command, \
                 patch.object(infrastructure_retry.time,'sleep') as wait:
                with self.assertRaises(scheduler.RedisError):
                    resilience.RedisVideoCheckpointStore._command('redis://fixture',None,'HGET','fixture','id')
                self.assertEqual(command.call_count,1);wait.assert_not_called()

    def test_asr_success_survives_remote_sync_fuse_without_becoming_asr_retry(self):
        self.run_asr_fixture('本视频介绍真实住宅项目户型与园林设计。','completed')

    def test_asr_failure_evidence_sync_outage_fuses_without_killing_queue_thread(self):
        self.run_asr_fixture('','retry_pending')

    def run_asr_fixture(self,text,expected_status):
        import channels_pc_collector as collector
        from dataclasses import asdict
        with tempfile.TemporaryDirectory() as folder, contextlib.redirect_stdout(io.StringIO()) as output:
            state=Path(folder)/'checkpoint.sqlite';wav=Path(folder)/'fixture.wav';wav.write_bytes(b'fixture')
            db=collector.init_state(state)
            job=collector.PendingClientAsr(wav_path=wav,title='fixture',prompt_context=None,duration=13,capture_seconds=13,
                recorder_seconds=13,recorder_audit={},seeked=False,reloaded_from_start=False,source='fixture')
            payload={**asdict(job),'wav_path':str(wav),'fingerprint':'fp','project':'fixture'}
            row=collector.ResultRow(keyword='fixture',project='fixture',title='fixture',url='https://weixin.qq.com/sph/fixture')
            collector.upsert_video_checkpoint(db,keyword='fixture',project='fixture',fingerprint='fp',status='retry_pending',retry_count=0,row=row)
            db.execute("INSERT INTO asr_job(article_key,keyword,wav_path,payload_json,status,attempts,created_at,updated_at) VALUES(?,?,?,?, 'pending',0,?,?)",
                ('article','fixture',str(wav),json.dumps(payload),'2026-10-19','2026-10-19'))
            db.commit();db.close()
            with patch.object(collector,'transcribe_pending_client_audio',return_value=text) as decode, \
                 patch.object(collector,'has_untrusted_transcript',return_value=False), \
                 patch.object(collector,'asr_output_needs_review',return_value=False), \
                 patch.object(collector.RedisVideoCheckpointStore,'put',side_effect=resilience.RedisCheckpointUnavailable('TimeoutError')):
                queue=collector.BackgroundAsrQueue(state,{},recovery_keyword='fixture')
                with self.assertRaises(resilience.RedisCheckpointUnavailable):queue.close_and_wait()
                decode.assert_called_once()
            db=collector.init_state(state)
            job_state=db.execute('SELECT status,attempts FROM asr_job').fetchone()
            checkpoint=collector.load_video_checkpoints(db,'fixture')['fp'];db.close()
            self.assertEqual(job_state,(expected_status,1));self.assertEqual(checkpoint['status'],expected_status)
            if text:self.assertIn('本视频',checkpoint['row']['video_content'])
            self.assertTrue(wav.exists())
            self.assertIn('client_audio_asr_remote_sync_paused',output.getvalue())
            self.assertNotIn('client_audio_asr_job_persisted_failure',output.getvalue())


if __name__=='__main__':unittest.main()
