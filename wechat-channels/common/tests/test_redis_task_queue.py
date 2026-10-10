import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


SOURCE = Path(__file__).parents[1] / "src" / "redis_task_queue.py"
SPEC = importlib.util.spec_from_file_location("redis_task_queue_tests", SOURCE)
queue = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = queue
SPEC.loader.exec_module(queue)


def redis_hash(values):
    output = []
    for index, value in enumerate(values):
        output.extend((f"fingerprint-{index}", json.dumps(value)))
    return output


class RedisCompletionGuardTests(unittest.TestCase):
    def setUp(self):
        self.args = SimpleNamespace(
            prefix="wechat:channels:test-run",
            redis_url="redis://127.0.0.1:6379/0",
            redis_password="secret",
        )
        self.item = {"task_id": "topic1:abc", "keyword": "中海 住宅"}

    def guard_for(self, values):
        def redis_reply(_url, _password, command, *_args, **_kwargs):
            if command == "HGETALL":
                return redis_hash(values)
            if command == "EVAL":
                return "retry-message-id"
            raise AssertionError(command)
        with patch.object(queue, "redis_command", side_effect=redis_reply):
            return queue.checkpoint_completion_guard(self.args, self.item)

    def test_completed_metadata_is_staged_then_allows_xack(self):
        result = self.guard_for([
            {"status": "completed"},
            {"status": "completed_metadata", "row": {"title": "真实视频"}},
        ])
        self.assertTrue(result["ok"])
        self.assertEqual(result["blocking"], {})
        self.assertEqual(result["deferredCount"], 1)
        self.assertEqual(result["deferredStaged"], 1)

    def test_retry_pending_is_staged_then_allows_xack(self):
        result = self.guard_for([
            {"status": "retry_pending", "title": "可定位视频"},
            {"status": "completed"},
        ])
        self.assertTrue(result["ok"])
        self.assertEqual(result["blocking"], {})
        self.assertEqual(result["deferredCount"], 1)

    def test_identityless_deferred_placeholder_is_not_staged(self):
        result = self.guard_for([
            {"status": "retry_pending", "row": None, "title": ""},
            {"status": "completed_metadata", "row": {"title": "真实视频"}},
        ])
        self.assertTrue(result["ok"])
        self.assertEqual(result["deferredCount"], 1)
        self.assertEqual(result["deferredStaged"], 1)
        self.assertEqual(result["invalidDeferredIdentitySkipped"], 1)

    def test_all_terminal_checkpoints_allow_xack(self):
        result = self.guard_for([
            {"status": "completed"},
            {"status": "dead_letter"},
            {"status": "no_content"},
        ])
        self.assertTrue(result["ok"])
        self.assertEqual(result["blocking"], {})

    def test_empty_checkpoint_hash_allows_true_empty_result(self):
        result = self.guard_for([])
        self.assertTrue(result["ok"])
        self.assertEqual(result["checkpointCount"], 0)

    def test_malformed_checkpoint_fails_closed(self):
        with patch.object(
            queue, "redis_command", return_value=["fingerprint", "not-json"]
        ):
            result = queue.checkpoint_completion_guard(self.args, self.item)
        self.assertFalse(result["ok"])
        self.assertEqual(result["blocking"], {"invalid_json": 1})

    def test_task_id_uses_same_safe_token_as_checkpoint_store(self):
        with patch.object(queue, "redis_command", return_value=[]) as command:
            queue.checkpoint_completion_guard(self.args, self.item)
        self.assertEqual(
            command.call_args.args[-1],
            "wechat:channels:test-run:video-state:topic1_abc",
        )

    def test_unknown_checkpoint_state_still_blocks_xack(self):
        result = self.guard_for([{"status": "future_unrecognized_state"}])
        self.assertFalse(result["ok"])
        self.assertEqual(result["blocking"], {"future_unrecognized_state": 1})

    def test_scheduler_recovers_one_stale_primary_before_new_work(self):
        args = SimpleNamespace(
            redis_url="redis://127.0.0.1:6379/0",
            redis_password="secret",
            stream="primary-stream",
            group="primary-group",
            consumer="worker-01-test",
            reclaim_idle_seconds=300,
            block_seconds=1,
        )
        stale = ("1-0", {"task_id": "topic1:old", "keyword": "旧任务"})
        with patch.object(queue, "auto_claim", return_value=stale) as reclaim, patch.object(
            queue, "read_new"
        ) as read_new:
            message, recovered = queue.claim_primary_message(
                args, recover_stale_pending=True
            )
        self.assertEqual(message, stale)
        self.assertTrue(recovered)
        reclaim.assert_called_once()
        read_new.assert_not_called()

        fresh = ("2-0", {"task_id": "topic1:new", "keyword": "新任务"})
        with patch.object(queue, "auto_claim") as reclaim, patch.object(
            queue, "read_new", return_value=fresh
        ) as read_new:
            message, recovered = queue.claim_primary_message(
                args, recover_stale_pending=False
            )
        self.assertEqual(message, fresh)
        self.assertFalse(recovered)
        read_new.assert_called_once()
        reclaim.assert_not_called()

    def test_central_log_redacts_credentials_and_is_bounded(self):
        args = SimpleNamespace(
            redis_url="redis://127.0.0.1:6379/0",
            redis_password="redis-secret",
            log_stream="wechat:channels:test:logs",
            log_maxlen=200000,
            consumer="worker-01-test",
            worker_root=Path("worker-01"),
        )
        with patch.dict(os.environ, {"MYSQL_PASSWORD": "mysql-secret"}), patch.object(
            queue, "redis_command", return_value="1-0"
        ) as command:
            ok = queue.publish_remote_log(
                args,
                "worker_output",
                message="redis-secret and mysql-secret",
                item={"task_id": "topic1:abc", "topic": "topic1", "keyword": "中海 住宅"},
            )
        self.assertTrue(ok)
        # The first two function arguments are the Redis connection and its
        # authentication secret; only the XADD payload is persisted remotely.
        serialized = " ".join(map(str, command.call_args.args[2:]))
        self.assertNotIn("redis-secret", serialized)
        self.assertNotIn("mysql-secret", serialized)
        self.assertIn("MAXLEN", command.call_args.args)

    def test_primary_and_retry_tasks_keep_distinct_entry_points(self):
        self.assertEqual(queue.worker_script_for_task_kind("primary"), "run-worker.ps1")
        self.assertEqual(
            queue.worker_script_for_task_kind("video_retry"),
            "run-asr-backfill.ps1",
        )

    def test_persistent_asr_service_is_reused_between_video_tasks(self):
        args = SimpleNamespace(common=SOURCE.parents[1])
        service = queue.PersistentAsrService(args)

        class RunningProcess:
            @staticmethod
            def poll():
                return None

        service.process = RunningProcess()
        service.host = "127.0.0.1"
        service.port = 43123
        service.instance = "same-model-instance"
        with patch.object(queue.subprocess, "Popen") as launch:
            first = service.ensure_started()
            second = service.ensure_started()
        launch.assert_not_called()
        self.assertEqual(first, second)
        self.assertEqual(first["WECHAT_PERSISTENT_ASR_PORT"], "43123")
        self.assertEqual(
            first["WECHAT_PERSISTENT_ASR_INSTANCE"], "same-model-instance"
        )
        # Avoid the atexit cleanup treating the lightweight test double as a
        # real subprocess.
        service.process = None
        service.port = None

    def test_cross_machine_retry_hydrates_when_local_sqlite_has_no_row(self):
        script = (SOURCE.parents[1] / "run-asr-backfill.ps1").read_text(
            encoding="utf-8-sig"
        )
        self.assertIn(
            "(-not $hasLocalRows) -and (-not $env:WECHAT_REDIS_VIDEO_FINGERPRINT)",
            script,
        )
        self.assertIn(
            "(-not (Test-Path $stateDb)) -and (-not $env:WECHAT_REDIS_VIDEO_FINGERPRINT)",
            script,
        )
        self.assertIn("hydrat", script.lower())

    def test_scheduler_supports_fair_mixed_and_dedicated_asr_roles(self):
        parser = queue.build_parser()
        source = SOURCE.read_text(encoding="utf-8")
        self.assertIn('choices=("mixed", "primary", "asr")', source)
        self.assertIn('primary_since_retry >= primary_burst', source)
        self.assertIsNotNone(parser)

    def test_distributed_defaults_make_all_three_nodes_full_pipeline_workers(self):
        script = (SOURCE.parents[1] / "run-redis-worker.ps1").read_text(
            encoding="utf-8-sig"
        )
        self.assertIn("$env:REDIS_WORKER_ROLE = 'mixed'", script)
        self.assertNotIn("@('worker-02','worker-03')", script)
        self.assertIn("$env:REDIS_PRIMARY_BURST = '1'", script)

    def test_persistent_asr_service_is_attached_to_primary_and_retry_tasks(self):
        source = SOURCE.read_text(encoding="utf-8-sig")
        self.assertIn(
            'task_kind in {"primary", "video_retry"} and asr_service is not None',
            source,
        )

    def test_parent_keyword_is_not_final_while_another_video_is_pending(self):
        item = {
            "task_id": "topic2:abc",
            "source_task_id": "topic2:abc",
            "topic": "topic2",
            "keyword": "华润臻澐",
        }
        completed = json.dumps({"status": "completed"})
        pending = json.dumps({"status": "retry_pending"})
        with patch.object(
            queue, "redis_command",
            side_effect=[["one", completed, "two", pending], 1],
        ):
            result = queue.refresh_parent_keyword_status(self.args, item)
        self.assertEqual(result["status"], "completed_with_deferred_retries")
        self.assertEqual(result["unresolvedVideoCount"], 1)

    def test_parent_keyword_exposes_dead_letters_instead_of_plain_complete(self):
        item = {
            "task_id": "topic2:abc",
            "source_task_id": "topic2:abc",
            "topic": "topic2",
            "keyword": "华润臻澐",
        }
        dead = json.dumps({"status": "dead_letter"})
        with patch.object(
            queue, "redis_command", side_effect=[["one", dead], 1],
        ):
            result = queue.refresh_parent_keyword_status(self.args, item)
        self.assertEqual(result["status"], "completed_with_dead_letters")
        self.assertEqual(result["deadLetterCount"], 1)

    def test_video_retry_passes_original_result_index_to_collector(self):
        source = SOURCE.read_text(encoding="utf-8")
        self.assertIn('env["WECHAT_REDIS_VIDEO_RESULT_INDEX"]', source)

    def test_scheduler_passes_resolved_redis_connection_to_child(self):
        source = SOURCE.read_text(encoding="utf-8-sig")
        self.assertIn('env["REDIS_URL"] = str(args.redis_url)', source)
        self.assertIn('env["REDIS_PASSWORD"] = str(args.redis_password)', source)
        self.assertIn('checkpoint.get("result_index")', source)
        self.assertIn('env["REDIS_RUN_ID"] = str(args.run_id)', source)

    def test_group_lag_is_read_from_xinfo(self):
        reply = [["name", "channels-workers", "consumers", 1, "pending", 0, "lag", 2]]
        with patch.object(queue, "redis_command", return_value=reply):
            self.assertEqual(
                queue.group_lag(
                    self.args.redis_url, self.args.redis_password,
                    "stream", "channels-workers",
                ),
                2,
            )

    def test_reset_generation_is_created_once_and_reused(self):
        with patch.object(
            queue, "redis_command", side_effect=[None, "OK", "generation-1"],
        ) as command:
            generation = queue.ensure_run_generation(
                self.args.redis_url, self.args.redis_password, self.args.prefix,
            )
        self.assertEqual(generation, "generation-1")
        self.assertEqual(command.call_args_list[1].args[2:], (
            "SET", "wechat:channels:test-run:generation",
            command.call_args_list[1].args[4], "NX",
        ))

    def test_video_retry_ack_requires_exact_terminal_fingerprint(self):
        item = {
            "task_id": "topic1:abc",
            "source_task_id": "topic1:abc",
            "fingerprint": "fingerprint-1",
        }
        with patch.object(
            queue, "redis_command",
            return_value=json.dumps({"status": "completed", "retry_count": 1}),
        ):
            result = queue.video_retry_completion_guard(self.args, item)
        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "completed")

        with patch.object(
            queue, "redis_command",
            return_value=json.dumps({"status": "retry_pending", "retry_count": 2}),
        ):
            result = queue.video_retry_completion_guard(self.args, item)
        self.assertFalse(result["ok"])
        self.assertEqual(result["retryCount"], 2)

    def test_safe_stopped_partial_task_stages_asr_and_does_not_claim_next(self):
        """Salvaged metadata must keep both its ASR work and outer stop."""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            queue_path = root / "queue.json"
            queue_path.write_text(json.dumps({"tasks": []}), encoding="utf-8")
            args = SimpleNamespace(
                queue=queue_path,
                common=root,
                worker_root=root / "worker-02",
                redis_url="redis://127.0.0.1:6379/0",
                redis_password="secret",
                stream="wechat:channels:test-run:tasks",
                group="channels-workers",
                retry_stream="wechat:channels:test-run:video-retry",
                retry_group="channels-workers-video-retry",
                seeded_key="wechat:channels:test-run:seeded",
                status_key="wechat:channels:test-run:status",
                consumer="worker-02-test",
                reclaim_idle_seconds=300,
                heartbeat_seconds=30,
                heartbeat_failure_limit=3,
                block_seconds=1,
                once=False,
            )
            item = {
                "task_id": "topic1:abc",
                "topic": "topic1",
                "keyword": "中海地产 住宅",
                "queue": {"tasks": []},
            }
            guard = {
                "ok": True,
                "checkpointCount": 67,
                "statuses": {"completed_metadata": 67},
                "blocking": {},
                "deferredCount": 67,
                "deferredStaged": 67,
            }

            def stopped_child(*_args, **_kwargs):
                stop_file = args.worker_root / ".state" / "stop.requested"
                stop_file.parent.mkdir(parents=True, exist_ok=True)
                stop_file.write_text("stop", encoding="utf-8")
                return 4

            with patch.object(queue, "ensure_group"), patch.object(
                queue, "seed_tasks", return_value=0,
            ), patch.object(
                queue, "read_new", return_value=("1-0", item),
            ) as read_new, patch.object(
                queue, "run_task", side_effect=stopped_child,
            ), patch.object(
                queue, "checkpoint_completion_guard", return_value=guard,
            ) as completion_guard, patch.object(
                queue, "update_remote_status",
            ) as update_status, patch.object(
                queue, "redis_command",
            ) as redis_command:
                result = queue.run_worker(args)

            self.assertEqual(result, 130)
            completion_guard.assert_called_once_with(args, item)
            self.assertEqual(read_new.call_count, 1)
            self.assertFalse(any(
                call.args[2:3] == ("XACK",) for call in redis_command.call_args_list
            ))
            update_status.assert_called_once()
            self.assertEqual(update_status.call_args.args[2], "retry_pending")
            self.assertEqual(
                update_status.call_args.args[3]["checkpointGuard"]["deferredStaged"],
                67,
            )
            state = json.loads(
                (args.worker_root / ".state" / "redis_worker_status.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(state["status"], "stopped")


if __name__ == "__main__":
    unittest.main()
