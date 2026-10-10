import unittest
import json
from pathlib import Path


COMMON = Path(__file__).parents[1]


class WorkerScriptTests(unittest.TestCase):
    def test_redis_worker_loads_per_worker_credential_before_prompting(self):
        worker = (Path(__file__).parents[1] / "run-redis-worker.ps1").read_text(
            encoding="utf-8-sig"
        )
        credential_load = worker.index(".credentials\\redis-password.txt")
        password_prompt = worker.index("Read-Host 'Redis password")
        self.assertLess(credential_load, password_prompt)
        self.assertIn("Get-Content -LiteralPath $redisCredentialFile -Raw", worker)

    def test_redis_launcher_honours_queue_override(self):
        worker = (COMMON / "run-redis-worker.ps1").read_text(encoding="utf-8-sig")
        self.assertIn("if ($env:WECHAT_QUEUE_FILE)", worker)
        self.assertIn("Resolve-Path $env:WECHAT_QUEUE_FILE", worker)
        self.assertIn('Write-Host "Redis task queue: $Queue"', worker)

    def test_redis_child_does_not_erase_outer_safe_stop_marker(self):
        worker = (COMMON / "run-worker.ps1").read_text(encoding="utf-8-sig")
        self.assertIn("if (-not $redisStateScope)", worker)
        self.assertIn(
            "Remove-Item $stopFile -Force -ErrorAction SilentlyContinue", worker
        )

    def test_absolute_keyword_file_is_not_joined_to_package_root(self):
        source = (COMMON / "run-worker.ps1").read_text(encoding="utf-8-sig")
        self.assertIn("[System.IO.Path]::IsPathRooted", source)
        self.assertIn("[System.IO.Path]::GetFullPath", source)
        self.assertNotIn("$taskFile = Join-Path $Root $task.keywordsFile", source)

    def test_incremental_updater_includes_process_loopback_runtime(self):
        source = (
            COMMON.parent / "应用20260928窗口与Redis修复.ps1"
        ).read_text(encoding="utf-8-sig")
        self.assertIn("common\\src\\loopback-recorder.py", source)
        self.assertIn("common\\src\\process-loopback-recorder.exe", source)
        self.assertIn("common\\src\\asr-worker.py", source)
        self.assertIn("common\\check-env.ps1", source)
        self.assertNotIn('throw "Target file missing:', source)

    def test_redis_reset_generation_isolates_local_state(self):
        worker = (COMMON / "run-worker.ps1").read_text(encoding="utf-8-sig")
        asr = (COMMON / "run-asr-backfill.ps1").read_text(encoding="utf-8-sig")
        for source in (worker, asr):
            self.assertIn("WECHAT_REDIS_STATE_SCOPE", source)
            self.assertIn(".state\\redis-runs\\", source)
            self.assertIn("runs\\redis-runs\\", source)

    def test_keyword_transition_uses_random_configured_jitter(self):
        source = (COMMON / "run-worker.ps1").read_text(encoding="utf-8-sig")
        self.assertIn("jitter_keyword_transition_seconds", source)
        self.assertIn("Get-Random -Minimum $keywordTransitionMinSeconds", source)
        self.assertIn("Keyword transition jitter", source)

    def test_primary_visit_records_full_audio_and_defers_only_transcription(self):
        worker = (COMMON / "run-worker.ps1").read_text(encoding="utf-8-sig")
        config = json.loads((COMMON / "collector_config.json").read_text(encoding="utf-8"))
        collector = (COMMON / "src" / "channels_pc_collector.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("$env:WECHAT_CLIENT_ASR = '1'", worker)
        self.assertTrue(config["enable_client_asr"])
        self.assertTrue(config["client_asr_background"])
        self.assertTrue(config["client_asr_force_full_playback"])
        self.assertTrue(config["client_asr_collect_detail_during_recording"])
        self.assertIn("detail_fields_collected_during_audio_capture", collector)
        self.assertIn("during_capture_callback=", collector)

    def test_exact_asr_retry_bypasses_normal_cross_keyword_skip(self):
        collector = (COMMON / "src" / "channels_pc_collector.py").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            "and not (asr_backfill_mode and retry_fingerprint)", collector
        )

    def test_legacy_two_stage_launcher_now_runs_integrated_capture_once(self):
        launcher = (COMMON / "run-two-stage.ps1").read_text(encoding="utf-8-sig")
        self.assertIn("$env:WECHAT_CLIENT_ASR = '1'", launcher)
        self.assertNotIn("$env:WECHAT_CLIENT_ASR = '0'", launcher)
        self.assertEqual(launcher.count("run-worker.ps1"), 1)
        self.assertNotIn("run-asr-backfill.ps1') -Mode run", launcher)

    def test_direct_asr_reads_atomic_status_file_instead_of_mixed_stdout(self):
        source = (COMMON / "run-asr-backfill.ps1").read_text(encoding="utf-8-sig")
        self.assertIn("--status-file $directIngestStatus", source)
        self.assertIn("Get-Content -LiteralPath $directIngestStatus -Raw", source)
        self.assertNotIn("$directIngestText | ConvertFrom-Json", source)

    def test_mysql_import_has_utf8mb3_compatibility_fallback(self):
        source = (COMMON / "src" / "mysql-import.mjs").read_text(encoding="utf-8")
        self.assertIn("information_schema.COLUMNS", source)
        self.assertIn("legacyUtf8mb3Columns", source)
        self.assertIn("/[\\u{10000}-\\u{10FFFF}]/gu", source)
        for ddl_name in ("ods_social_media_post.sql", "ods_social_media_comment.sql"):
            ddl = (COMMON / "sql" / ddl_name).read_text(encoding="utf-8-sig")
            self.assertNotIn("utf8mb3", ddl)
            self.assertIn("utf8mb4_unicode_ci", ddl)


if __name__ == "__main__":
    unittest.main()
