import unittest
import json
import os
import shutil
import subprocess
import tempfile
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

    def test_legacy_date_cutoff_reports_cannot_bypass_collection_and_are_preserved(self):
        worker = (COMMON / 'run-worker.ps1').read_text(encoding='utf-8-sig')
        self.assertIn("$CompletionSchemaVersion = 'channels-pagination-v8-bound-search-end'", worker)
        self.assertIn('$oldKeyword.completionSchemaVersion -eq $CompletionSchemaVersion', worker)
        archive = worker.index("$legacyHistory = Join-Path $outDir 'acceptance-history'")
        self.assertLess(archive, worker.index("$ks = [ordered]@{keyword=$allowedKeyword"))
        self.assertIn('Copy-Item -LiteralPath $keywordStatusPath -Destination $legacyStatusBackup', worker)
        self.assertIn("throw 'Legacy keyword report evidence mismatch; refusing overwrite'", worker)

    def test_primary_and_backfill_use_same_nonsecret_database_defaults_as_verifier(self):
        for name in ('run-worker.ps1', 'run-asr-backfill.ps1'):
            source = (COMMON / name).read_text(encoding='utf-8-sig')
            self.assertIn("Join-Path $Common 'src\\mysql-defaults.json'", source)
            for setting in ('host', 'port', 'database'):
                self.assertIn('[string]$mysqlDefaults.' + setting, source)
            self.assertNotIn("$env:MYSQL_HOST = '127.0.0.1'", source)

    @unittest.skipUnless(os.name == 'nt' and shutil.which('powershell.exe'), 'Windows PowerShell fixture')
    def test_real_powershell_report_archive_is_byte_exact_idempotent_and_rejects_bad_backup(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            original = root / 'keyword_status.json'
            content = b'{"status":"completed","oldEvidence":"fixture","completionSchemaVersion":"v5"}\r\n'
            original.write_bytes(content)
            script = r'''
$ErrorActionPreference='Stop'
$outDir=$env:ARCHIVE_FIXTURE_ROOT
$keywordStatusPath=Join-Path $outDir 'keyword_status.json'
$oldKeyword=Get-Content -LiteralPath $keywordStatusPath -Raw | ConvertFrom-Json
$CompletionSchemaVersion='channels-pagination-v8-bound-search-end'
$tokens=$null;$errors=$null
$tree=[System.Management.Automation.Language.Parser]::ParseFile($env:ARCHIVE_FIXTURE_SOURCE,[ref]$tokens,[ref]$errors)
if($errors.Count){throw 'Fixture parse failed'}
$hashFunctions=@($tree.FindAll({param($node) $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Get-StatusEvidenceHash'},$true))
if($hashFunctions.Count -ne 1){throw 'Exact evidence hash helper not found'}
. ([ScriptBlock]::Create($hashFunctions[0].Extent.Text))
$blocks=@($tree.FindAll({param($node) $node -is [System.Management.Automation.Language.IfStatementAst] -and $node.Extent.Text.StartsWith('if ((Test-Path -LiteralPath $keywordStatusPath)')},$true))
if($blocks.Count -ne 1){throw 'Exact archival branch not found'}
& ([ScriptBlock]::Create($blocks[0].Extent.Text))
'''
            env = {**os.environ, 'ARCHIVE_FIXTURE_ROOT': folder,
                   'ARCHIVE_FIXTURE_SOURCE': str(COMMON / 'run-worker.ps1')}
            def run_fixture():
                return subprocess.run(['powershell.exe', '-NoProfile', '-Command', script],
                    env=env, capture_output=True, text=True, timeout=20,
                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            for _ in range(2):
                result = run_fixture()
                self.assertEqual(result.returncode, 0, 'Isolated archive branch failed: ' + result.stderr)
            backups = list((root / 'acceptance-history').glob('*.json'))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].read_bytes(), content)
            self.assertEqual(original.read_bytes(), content)
            backups[0].write_bytes(b'corrupted fixture backup')
            self.assertNotEqual(run_fixture().returncode, 0)
            self.assertEqual(original.read_bytes(), content)

    def test_absolute_keyword_file_is_not_joined_to_package_root(self):
        source = (COMMON / "run-worker.ps1").read_text(encoding="utf-8-sig")
        self.assertIn("[System.IO.Path]::IsPathRooted", source)
        self.assertIn("[System.IO.Path]::GetFullPath", source)
        self.assertNotIn("$taskFile = Join-Path $Root $task.keywordsFile", source)

    @unittest.skipUnless(
        (COMMON.parent / "应用20260928窗口与Redis修复.ps1").is_file(),
        "deployment-only historical updater is not included in the source repository",
    )
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
