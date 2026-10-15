import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parents[1]/'src'))
import channels_pc_collector as c

class RetryRepairTests(unittest.TestCase):
    def test_precise_retry_scroll_probe_has_own_bound_without_mutating_annual_config(self):
        original={'load_more_rounds':30,'load_more_search_recovery_attempts':4,'other':7}
        bounded=c.precise_retry_load_config(original)
        self.assertEqual(bounded['load_more_rounds'],6)
        self.assertEqual(bounded['load_more_search_recovery_attempts'],1)
        self.assertEqual(original['load_more_rounds'],30)
        self.assertEqual(bounded['other'],7)
        self.assertEqual(c.precise_retry_load_config({'load_more_rounds':1})['load_more_rounds'],3)

    def test_precise_verified_search_miss_consumes_budget_and_preserves_identity(self):
        import json
        from unittest.mock import patch
        from contextlib import closing
        from dataclasses import asdict
        with tempfile.TemporaryDirectory() as folder, closing(c.init_state(Path(folder)/'state.sqlite')) as db:
            row=c.ResultRow(project='test',keyword='test',url='https://example.invalid/exact',title='exact title',author_name='author')
            c.upsert_video_checkpoint(db,keyword='test',project='test',fingerprint='fp',
                status='retry_pending',retry_count=1,row=row)
            for status in ['partial_stopped','partial_login_required','partial_identity_recovery_required']:
                self.assertIsNone(c.record_precise_search_miss(db,keyword='test',project='test',retry_fingerprint='fp',scan_status=status,seen_fingerprints=set(),max_attempts=3))
            self.assertIsNone(c.record_precise_search_miss(db,keyword='test',project='test',retry_fingerprint='fp',scan_status='partial_retry_target_not_found',seen_fingerprints={'fp'},max_attempts=3))
            result=c.record_precise_search_miss(db,keyword='test',project='test',retry_fingerprint='fp',scan_status='partial_retry_target_not_found',seen_fingerprints=set(),max_attempts=3)
            self.assertEqual(result,('retry_pending',2))
            result=c.record_precise_search_miss(db,keyword='test',project='test',retry_fingerprint='fp',scan_status='partial_retry_target_not_found',seen_fingerprints=set(),max_attempts=3)
            self.assertEqual(result,('dead_letter',3))
            cp=c.load_video_checkpoints(db,'test')['fp']
            self.assertEqual(cp['article_key'],c.article_key_for_row(row));self.assertEqual(cp['row'],asdict(row))
            import video_retry_budget as budget
            self.assertTrue(budget.is_content_failure({'status':cp['status'],'reason':cp['last_error']}))

    def test_background_pending_job_cannot_revive_explicit_skip(self):
        import json
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as folder:
            file=Path(folder)/'state.sqlite';wav=Path(folder)/'fixture.wav';wav.write_bytes(b'RIFF')
            db=c.init_state(file)
            payload={'wav_path':str(wav),'title':'fixture','duration':53,'capture_seconds':54,
                     'recorder_seconds':54,'recorder_audit':{},'source':'test','fingerprint':'fp','project':'test'}
            c.upsert_video_checkpoint(db,keyword='test',project='test',fingerprint='fp',status='skipped_unresolved',retry_count=3,last_error='retained evidence')
            db.execute("INSERT INTO asr_job(article_key,keyword,wav_path,payload_json,status,attempts,created_at,updated_at) VALUES(?,?,?,?, 'pending',3,?,?)",
                       ('fixture','test',str(wav),json.dumps(payload),'2026-10-13','2026-10-13'))
            db.commit();db.close()
            with patch.object(c,'transcribe_pending_client_audio') as transcribe:
                queue=c.BackgroundAsrQueue(file,{'asr_job_max_attempts':3},recovery_keyword='test')
                queue.close_and_wait()
                transcribe.assert_not_called()
            db=c.init_state(file)
            try:
                self.assertEqual(db.execute("SELECT status,retry_count,last_error FROM video_checkpoint").fetchone(),('skipped_unresolved',3,'retained evidence'))
                self.assertEqual(db.execute("SELECT status,attempts FROM asr_job").fetchone(),('skipped_unresolved',3))
            finally:db.close()

    def test_dead_letter_requires_explicit_disposition_before_ack(self):
        import json
        import redis_task_queue as q
        from types import SimpleNamespace
        from unittest.mock import patch
        args=SimpleNamespace(prefix='fixture',redis_url='fixture',redis_password='fixture')
        item={'task_id':'test','fingerprint':'fp'}
        for count in (0,3):
            with patch.object(q,'redis_command',return_value=json.dumps({'status':'dead_letter','retry_count':count,'last_error':'ASR_QUALITY_REVIEW_REQUIRED'})):
                guard=q.video_retry_completion_guard(args,item)
            self.assertFalse(guard['ok'])
            self.assertFalse(guard['accepted'])
        with patch.object(q,'redis_command',return_value=json.dumps({'status':'skipped_unresolved','retry_count':3})):
            self.assertTrue(q.video_retry_completion_guard(args,item)['ok'])

    def test_legacy_parent_status_is_not_annual_scan_proof(self):
        import json
        import redis_task_queue as q
        from types import SimpleNamespace
        from unittest.mock import patch
        args=SimpleNamespace(prefix='fixture',redis_url='fixture',redis_password='fixture')
        item={'task_id':'test','fingerprint':'fp'}
        with patch.object(q,'update_remote_status'),patch.object(q,'redis_command',side_effect=[['fp',json.dumps({'status':'completed'})],json.dumps({'status':'completed_with_deferred_retries'})]):
            result=q.refresh_parent_keyword_status(args,item)
        self.assertEqual(result['status'],'retry_pending')
        self.assertFalse(result['scanCompleted'])

    def test_background_failure_publishes_actual_asr_attempts(self):
        import json
        from unittest.mock import patch,MagicMock
        with tempfile.TemporaryDirectory() as folder:
            file=Path(folder)/'state.sqlite'
            wav=Path(folder)/'fixture.wav';wav.write_bytes(b'RIFF')
            db=c.init_state(file)
            payload={'wav_path':str(wav),'title':'fixture','duration':53,'capture_seconds':54,
                     'recorder_seconds':54,'recorder_audit':{},'source':'test','fingerprint':'fp','project':'test'}
            c.upsert_video_checkpoint(db,keyword='test',project='test',fingerprint='fp',status='retry_pending',retry_count=0)
            db.execute("INSERT INTO asr_job(article_key,keyword,wav_path,payload_json,status,attempts,created_at,updated_at) VALUES(?,?,?,?, 'pending',2,?,?)",
                       ('fixture','test',str(wav),json.dumps(payload),'2026-10-13','2026-10-13'))
            db.commit();db.close()
            remote=MagicMock()
            with patch.object(c,'RedisVideoCheckpointStore',return_value=remote),patch.object(c,'transcribe_pending_client_audio',side_effect=RuntimeError('ASR_QUALITY_REVIEW_REQUIRED')):
                queue=c.BackgroundAsrQueue(file,{'asr_job_max_attempts':3},recovery_keyword='test')
                queue.close_and_wait()
            db=c.init_state(file)
            try:
                row=db.execute("SELECT status,retry_count FROM video_checkpoint WHERE keyword='test' AND fingerprint='fp'").fetchone()
                self.assertEqual(row,('dead_letter',3))
                self.assertEqual(remote.put.call_args.args[1]['retry_count'],3)
            finally:db.close()

    def test_empty_or_short_decode_reaches_bounded_failure_not_no_content(self):
        import json
        from unittest.mock import patch,MagicMock
        for decoded in ('','过短的口播内容'):
            with self.subTest(decoded=decoded),tempfile.TemporaryDirectory() as folder:
                file=Path(folder)/'state.sqlite';wav=Path(folder)/'fixture.wav';wav.write_bytes(b'RIFF')
                db=c.init_state(file)
                payload={'wav_path':str(wav),'title':'fixture','duration':53,'capture_seconds':54,
                         'recorder_seconds':54,'recorder_audit':{},'source':'test','fingerprint':'fp','project':'test'}
                c.upsert_video_checkpoint(db,keyword='test',project='test',fingerprint='fp',status='retry_pending',retry_count=0)
                db.execute("INSERT INTO asr_job(article_key,keyword,wav_path,payload_json,status,attempts,created_at,updated_at) VALUES(?,?,?,?, 'pending',2,?,?)",
                           ('fixture','test',str(wav),json.dumps(payload),'2026-10-13','2026-10-13'))
                db.commit();db.close()
                with patch.object(c,'RedisVideoCheckpointStore',return_value=MagicMock()),patch.object(c,'transcribe_pending_client_audio',return_value=decoded):
                    queue=c.BackgroundAsrQueue(file,{'asr_job_max_attempts':3},recovery_keyword='test')
                    queue.close_and_wait()
                db=c.init_state(file)
                try:
                    self.assertEqual(db.execute("SELECT status,retry_count FROM video_checkpoint").fetchone(),('dead_letter',3))
                    self.assertEqual(db.execute("SELECT status,attempts FROM asr_job").fetchone(),('dead_letter',3))
                finally:db.close()

    def test_only_known_content_failures_can_consume_budget(self):
        from video_retry_budget import is_content_failure
        self.assertTrue(is_content_failure({'status':'retry_pending','reason':'ASR transcript is implausibly short for captured duration'}))
        self.assertTrue(is_content_failure({'status':'retry_pending','reason':'ASR_QUALITY_REVIEW_REQUIRED'}))
        for reason in ['LOGIN_REQUIRED','ASR model initialization memory failure','MYSQL_IMPORT_FAILED','unknown','ASR_QUALITY_REVIEW_REQUIRED STOP_REQUESTED']:
            self.assertFalse(is_content_failure({'status':'retry_pending','reason':reason}))
        self.assertFalse(is_content_failure({'status':'missing_checkpoint','reason':'ASR_QUALITY_REVIEW_REQUIRED'}))

    def test_sparse_update_preserves_published_identity_and_retry_count(self):
        with tempfile.TemporaryDirectory() as folder:
            db=c.init_state(Path(folder)/'state.sqlite')
            try:
                row=c.ResultRow(project='隔离测试',keyword='关键词',title='真实身份',url='https://weixin.qq.com/sph/test',author_name='作者',video_duration=53)
                c.upsert_video_checkpoint(db,keyword=row.keyword,project=row.project,fingerprint='fp',status='retry_pending',retry_count=2,row=row,asr_status='partial_review')
                updated=c.upsert_video_checkpoint(db,keyword=row.keyword,project=row.project,fingerprint='fp',status='retry_pending',retry_count=0,last_error='再次失败')
                self.assertEqual(updated['retry_count'],2)
                self.assertEqual(updated['row']['title'],'真实身份')
                self.assertEqual(updated['row']['url'],row.url)
                self.assertEqual(updated['asr_status'],'partial_review')
                self.assertIsNotNone(updated['article_key'])
            finally:db.close()

    def test_mixed_foreign_gibberish_is_not_accepted_as_zh_transcript(self):
        value="සොියකAllāhාසින්තහාහ්අවෝාහිර්වperformance.，ʎSkelloh…ʎ"
        text,audit=c.assess_asr_text_quality(value,None,53,24,True)
        self.assertIsNone(text)
        self.assertEqual(audit['reason'],'unexpected_script_for_zh_decoder')

    def test_rejected_decoding_is_not_no_content(self):
        with self.assertRaisesRegex(RuntimeError,'ASR_QUALITY_REVIEW_REQUIRED'):
            c.require_trustworthy_asr_result(None,[{'raw_text_length':50,'quality':{'accepted':False,'reason':'unexpected_script'}}])
        c.require_trustworthy_asr_result(None,[{'raw_text_length':0,'quality':{'accepted':False,'reason':'empty'}}])
        with self.assertRaises(c.AsrQualityRejectedError):
            c.require_trustworthy_asr_result(None,[{'pass':'chunked_recovery','chunks':[
                {'text_length':0,'quality':{'accepted':False,'reason':'known_whisper_hallucination'}}]}])

    def test_known_subtitle_credit_hallucination_is_rejected(self):
        text,audit=c.assess_asr_text_quality("字幕by索兰娅",capture_seconds=54)
        self.assertIsNone(text)
        self.assertEqual(audit['reason'],'known_whisper_hallucination')

    def test_chunk_recovery_keeps_chinese_language(self):
        from unittest.mock import patch
        from types import SimpleNamespace
        class Model:
            def transcribe(self,_path,**options):
                self.options=options
                return iter([SimpleNamespace(text='真实口播内容')]),SimpleNamespace(duration_after_vad=8)
        model=Model()
        with tempfile.TemporaryDirectory() as folder:
            sample=Path(folder)/'fixture.wav'
            sample.touch()
            with patch.object(c,'extract_wav_slice',return_value=sample):
                c.transcribe_sparse_audio_in_chunks(model,sample,{'language':'zh'}, {},None,8)
        self.assertEqual(model.options['language'],'zh')

    def test_legacy_terminal_failure_does_not_block_all_keywords(self):
        from retry_priority import checkpoint_blocker
        self.assertIsNone(checkpoint_blocker({'status':'dead_letter','retry_count':3,'last_error':'detail failed'}))
        self.assertIsNotNone(checkpoint_blocker({'status':'dead_letter','retry_count':2,'last_error':'detail failed'}))
        self.assertEqual(checkpoint_blocker({'status':'dead_letter','retry_count':'bad','last_error':'detail failed'}),'invalid_retry_count')

    def test_rescan_cannot_revive_explicit_skip(self):
        with tempfile.TemporaryDirectory() as folder:
            db=c.init_state(Path(folder)/'state.sqlite')
            try:
                c.upsert_video_checkpoint(db,keyword='test',project='test',fingerprint='fp',status='skipped_unresolved',retry_count=3,last_error='retained')
                result=c.upsert_video_checkpoint(db,keyword='test',project='test',fingerprint='fp',status='retry_pending',retry_count=0)
                self.assertEqual(result['status'],'skipped_unresolved')
                self.assertEqual(result['last_error'],'retained')
                self.assertEqual(result['retry_count'],3)
            finally:db.close()

if __name__=='__main__':unittest.main()
