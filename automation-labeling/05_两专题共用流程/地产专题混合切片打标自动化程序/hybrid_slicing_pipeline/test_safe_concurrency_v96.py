"""Offline admission/recovery tests. No API requests or live checkpoint writes."""
import contextlib
import io
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
import resume_limited_v96 as launcher
import safe_concurrency_v96 as control


BODY = {"model": "qwen3.7-flash", "messages": [{"role": "user", "content": "原文"}],
        "enable_thinking": False, "max_tokens": 8192}


class ControlSafetyTests(unittest.TestCase):
    def test_authorized_ceiling(self):
        with self.assertRaises(ValueError):
            control.Governor(21)

    def test_input_output_and_context_limits(self):
        control.request_budget(BODY)
        for value in (0, 131073, None):
            with self.assertRaises(control.RequestBudgetError):
                control.request_budget({**BODY, "max_tokens": value})
        with self.assertRaises(control.RequestBudgetError):
            control.request_budget({**BODY, "messages": [{"content": "中" * 340000}]})
        with self.assertRaises(control.RequestBudgetError):
            control.request_budget({**BODY, "messages": [{"content": "a" * 960000}], "max_tokens": 131072})
        with self.assertRaises(control.RequestBudgetError):
            control.request_budget({**BODY, "enable_thinking": True})

    def test_inflight_reservations_do_not_expire(self):
        now = [0]
        g = control.Governor(tpm=100, clock=lambda: now[0])
        ticket = g.acquire(90)
        now[0] = 121
        self.assertEqual(g.snapshot()["local_reserved_tokens"], 90)
        g.finish(ticket)
        now[0] = 180
        self.assertEqual(g.snapshot()["local_reserved_tokens"], 90)
        now[0] = 182
        self.assertEqual(g.snapshot()["local_reserved_tokens"], 0)

    def test_completed_usage_replaces_estimate(self):
        g = control.Governor()
        ticket = g.acquire(50000)
        g.finish(ticket, {"prompt_tokens": 100, "completion_tokens": 10}, 200, 1)
        self.assertEqual(g.snapshot()["local_reserved_tokens"], 110)

    def test_unknown_usage_never_zero(self):
        g = control.Governor()
        ticket = g.acquire(50000)
        g.finish(ticket, {}, 429, 1)
        self.assertEqual(g.snapshot()["local_reserved_tokens"], 50000)
        self.assertEqual(g.snapshot()["effective_concurrency"], 15)
        self.assertGreater(g.snapshot()["cooldown_seconds"], 59)

    def test_timeout_and_latency_reduce_concurrency(self):
        g = control.Governor()
        g.finish(g.acquire(1), seconds=2, network_error=True)
        self.assertEqual(g.target, 15)
        g.cooldown_until = 0
        g.finish(g.acquire(1), status=200, seconds=65)
        self.assertEqual(g.target, 10)

    def test_no_auto_raise_above_twenty(self):
        now = [100]
        g = control.Governor(clock=lambda: now[0])
        for _ in range(40):
            g.finish(g.acquire(1), {"prompt_tokens": 1, "completion_tokens": 1}, 200, 1)
        self.assertEqual(g.target, 20)

    def test_rpm_and_tpm_wait_instead_of_send(self):
        for limits in ({"rpm": 1}, {"tpm": 100}):
            stopped = [False]
            g = control.Governor(stop=lambda: stopped[0], **limits)
            first = g.acquire(90)
            errors = []
            ready = threading.Event()
            def next_attempt():
                ready.set()
                try:
                    g.acquire(90)
                except control.SoftStop as exc:
                    errors.append(exc)
            worker = threading.Thread(target=next_attempt)
            worker.start()
            ready.wait(1)
            with g.cv:
                stopped[0] = True
                g.cv.notify_all()
            worker.join(1)
            self.assertEqual(len(errors), 1)
            self.assertEqual(g.total_attempts, 1)
            g.finish(first)

    def test_parallel_admission_never_exceeds_twenty(self):
        g = control.Governor()
        ids = [g.acquire(1) for _ in range(20)]
        stop = [False]
        g.stop = lambda: stop[0]
        errors = []
        def blocked_attempt():
            try:
                g.acquire(1)
            except control.SoftStop:
                errors.append(True)
        worker = threading.Thread(target=blocked_attempt)
        worker.start()
        with g.cv:
            stop[0] = True
            g.cv.notify_all()
        worker.join(1)
        self.assertEqual(errors, [True])
        self.assertEqual(g.snapshot()["peak_active_http_attempts"], 20)
        for ticket in ids:
            g.finish(ticket)

    def test_soft_stop_has_no_send_or_original_oserror_retry(self):
        post = Mock()
        wrapper = control.ControlledPost(post, control.Governor(stop=lambda: True), Path("unused"), Mock())
        with self.assertRaises(control.SoftStop):
            wrapper("http://unused", BODY, "not-a-secret")
        post.assert_not_called()
        self.assertFalse(issubclass(control.SoftStop, OSError))

    def test_budget_rejection_before_send(self):
        post = Mock()
        wrapper = control.ControlledPost(post, control.Governor(), Path("unused"), Mock())
        with self.assertRaises(control.RequestBudgetError):
            wrapper("http://unused", {**BODY, "max_tokens": 200000}, "not-a-secret")
        post.assert_not_called()

    def test_body_and_output_limits_unchanged_and_usage_saved(self):
        reply = Mock(status_code=200)
        reply.json.return_value = {"usage": {"prompt_tokens": 100, "completion_tokens": 2}}
        post, save = Mock(return_value=reply), Mock()
        g = control.Governor()
        wrapper = control.ControlledPost(post, g, Path("unused"), save)
        self.assertIs(wrapper("http://unused", BODY, "not-a-secret"), reply)
        self.assertIs(post.call_args.args[1], BODY)
        records = [c.args[1] for c in save.call_args_list if "attempt_id" in c.args[1]]
        self.assertEqual(records[-1]["usage"]["prompt_tokens"], 100)
        self.assertNotIn("not-a-secret", json.dumps(records))
        self.assertEqual(g.total_attempts, 1)

    def test_diagnostic_write_failure_prevents_send(self):
        post = Mock()
        g = control.Governor()
        wrapper = control.ControlledPost(post, g, Path("unused"), Mock(side_effect=OSError("disk full")))
        with self.assertRaisesRegex(RuntimeError, "no HTTP"):
            wrapper("http://unused", BODY, "not-a-secret")
        post.assert_not_called()
        self.assertEqual(g.snapshot()["active_http_attempts"], 0)

    def test_network_error_keeps_unknown_reservation(self):
        g = control.Governor()
        wrapper = control.ControlledPost(Mock(side_effect=TimeoutError()), g, Path("unused"), Mock())
        with self.assertRaises(TimeoutError):
            wrapper("http://unused", BODY, "not-a-secret")
        self.assertGreater(g.snapshot()["local_reserved_tokens"], 8192)
        self.assertEqual(g.target, 15)

    def test_cache_hit_sends_no_http(self):
        runner = launcher.b.ApiRunner(Path("unused"), key="not-a-secret")
        metric = {"status": "success"}
        with patch.object(Path, "exists", return_value=True), patch.object(Path, "read_text",
                return_value=json.dumps({"response": {"ok": True}, "metrics": metric})), \
                patch.object(launcher.b, "post_json") as post:
            result, actual = runner.call("system", {}, {"record_id": "1"}, "test")
        post.assert_not_called()
        self.assertEqual(result, {"ok": True})
        self.assertTrue(actual["cache_hit"])

    def test_original_retries_each_go_through_admission(self):
        replies = [Mock(status_code=429), Mock(status_code=200)]
        replies[0].json.return_value = {}
        replies[1].json.return_value = {"choices": [{"finish_reason": "stop", "message": {"content": "{}"}}],
                                        "usage": {"prompt_tokens": 10, "completion_tokens": 2}}
        g = control.Governor()
        def fake_post(*args, **kwargs):
            reply = replies.pop(0)
            if reply.status_code == 200:
                return reply
            return reply
        wrapper = control.ControlledPost(fake_post, g, Path("unused"), Mock())
        original_finish = g.finish
        def no_test_wait(*args, **kwargs):
            original_finish(*args, **kwargs)
            g.cooldown_until = 0
        runner = launcher.b.ApiRunner(Path("unused"), key="not-a-secret")
        with patch.object(Path, "exists", return_value=False), patch.object(launcher.b, "save_json"), \
                patch.object(launcher.b, "post_json", wrapper), patch.object(launcher.b.time, "sleep"), \
                patch.object(g, "finish", no_test_wait):
            result, metric = runner.call("system", {}, {"record_id": "1", "topic": "t", "kind": "文章"}, "test")
        self.assertEqual(g.total_attempts, 2)
        self.assertEqual(len(metric["attempts"]), 2)
        self.assertEqual(metric["status"], "success")

    def test_conflicts_require_python_exact_directory_and_other_pid(self):
        directory = Path("C:/specific/run")
        processes = [{"ProcessId": 1, "Name": "python.exe", "CommandLine": 'resume_missing_v96.py --output-dir "C:/specific/run"'},
                     {"ProcessId": 2, "Name": "powershell.exe", "CommandLine": 'resume_missing_v96.py C:/specific/run'},
                     {"ProcessId": 3, "Name": "python.exe", "CommandLine": 'resume_missing_v96.py C:/other/run'},
                     {"ProcessId": 4, "Name": "python.exe", "CommandLine": 'resume_limited_v96.py C:/specific/run'}]
        self.assertEqual(launcher.generator_conflicts(directory, processes, 4), [1])

    def test_single_instance_lock(self):
        with tempfile.TemporaryDirectory() as temp:
            with launcher.InstanceLock(Path(temp)):
                with self.assertRaisesRegex(RuntimeError, "single-instance"):
                    with launcher.InstanceLock(Path(temp)):
                        pass
            with launcher.InstanceLock(Path(temp)):
                pass


if __name__ == "__main__":
    unittest.main()
