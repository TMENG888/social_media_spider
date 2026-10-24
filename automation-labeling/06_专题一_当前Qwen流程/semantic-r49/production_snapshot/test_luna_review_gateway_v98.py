import json
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
import luna_review_gateway_v98 as m

SCHEMA = {'type': 'object', 'properties': {'ok': {'type': 'boolean'}}, 'required': ['ok'], 'additionalProperties': False}
DOC = {'record_id': 'synthetic-probe', 'topic': 'synthetic', 'kind': 'test'}


def reply(code=200, value=None, usage=True, headers=None):
    raw = {'status': 'completed', 'model': 'gpt-6-luna', 'output': [{'type': 'message', 'content':
        [{'type': 'output_text', 'text': json.dumps({'ok': True} if value is None else value)}]}]}
    if usage: raw['usage'] = {'input_tokens': 10, 'output_tokens': 3, 'total_tokens': 13, 'input_tokens_details': {'cached_tokens': 4}}
    return m.Reply(code, json.dumps(raw).encode(), headers or {})


class LunaGatewayTests(unittest.TestCase):
    def setUp(self): self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
    def runner(self, post, **kwargs):
        return m.LunaReviewRunner(self.tmp.name, key='synthetic-test-credential', post=post,
             sleep=lambda seconds: None, jitter=lambda: 0, min_interval=0, **kwargs)
    def call(self, runner): return runner.call('Synthetic only', {'source': 'test'}, DOC, 'test', SCHEMA)

    def test_missing_luna_key_does_not_use_qwen_key(self):
        with patch.dict('os.environ', {'LUNA_API_KEY': '', 'YS_LLM_API_KEY': 'do-not-send'}, clear=False):
            with self.assertRaises(ValueError): m.LunaReviewRunner(self.tmp.name)
    def test_ceiling(self):
        for concurrency in (0, 2, 3):
            with self.assertRaises(ValueError): self.runner(lambda *args: reply(), concurrency=concurrency)
    def test_no_double_v1(self):
        urls = []; runner = self.runner(lambda url, *args: urls.append(url) or reply()); self.call(runner)
        self.assertEqual(urls, ['https://in.aquria.cn:13003/v1/responses'])
    def test_unapproved_endpoint_not_credential_target(self):
        with self.assertRaises(ValueError): self.runner(lambda *args: reply(), base='https://other.example/v1')
    def test_no_qwen_only_parameters(self):
        body = self.runner(lambda *args: reply()).body('s', {}, SCHEMA)
        self.assertNotIn('enable_thinking', body); self.assertNotIn('temperature', body)
    def test_transient_failure_retried(self):
        calls = []; runner = self.runner(lambda *args: calls.append(1) or reply(503 if len(calls) == 1 else 200))
        _, metrics = self.call(runner); self.assertEqual(metrics['status'], 'success'); self.assertEqual(len(calls), 2)
    def test_401_not_retried_and_fatal(self):
        calls = []; runner = self.runner(lambda *args: calls.append(1) or reply(401))
        _, metrics = self.call(runner); self.assertEqual(len(calls), 1); self.assertTrue(runner.fatal.is_set())
        self.assertFalse(metrics['fallback_used'])
    def test_400_not_retried(self):
        calls = []; self.call(self.runner(lambda *args: calls.append(1) or reply(400))); self.assertEqual(len(calls), 1)
    def test_bounded_network_retries(self):
        calls = []
        def post(*args): calls.append(1); raise TimeoutError()
        _, metrics = self.call(self.runner(post)); self.assertEqual(len(calls), 4); self.assertEqual(metrics['unknown_attempt_usage'], 4)
    def test_schema_error_not_transport_resampled(self):
        calls = []; _, metrics = self.call(self.runner(lambda *args: calls.append(1) or reply(value={'wrong': True})))
        self.assertEqual(len(calls), 1); self.assertEqual(metrics['status'], 'failed_schema'); self.assertEqual(metrics['prompt_tokens'], 10)
    def test_success_cache_no_new_request(self):
        calls = []; runner = self.runner(lambda *args: calls.append(1) or reply()); self.call(runner)
        _, metrics = self.call(runner); self.assertEqual(len(calls), 1); self.assertTrue(metrics['cache_hit'])
    def test_unknown_usage_not_zero(self):
        _, metrics = self.call(self.runner(lambda *args: reply(usage=False)))
        self.assertIsNone(metrics['prompt_tokens']); self.assertIsNone(metrics['estimated_yuan']); self.assertEqual(metrics['unknown_attempt_usage'], 1)
    def test_cached_tokens_subset(self):
        _, metrics = self.call(self.runner(lambda *args: reply()))
        self.assertEqual(metrics['total_tokens'], 13); self.assertEqual(metrics['cached_input_tokens'], 4)
    def test_long_retry_after_not_shortened(self):
        calls = []; _, metrics = self.call(self.runner(lambda *args: calls.append(1) or reply(429, headers={'retry-after': '600'})))
        self.assertEqual(len(calls), 1); self.assertIn('Retry-After', metrics['error'])
    def test_date_retry_after(self):
        self.assertEqual(m.retry_after('Thu, 01 Jan 1970 00:01:00 GMT', now=0), 60)
    def test_no_secret_in_output_files(self):
        self.call(self.runner(lambda *args: reply()))
        text = ''.join(p.read_text(encoding='utf-8') for p in m.Path(self.tmp.name).rglob('*.json'))
        self.assertNotIn('synthetic-test-credential', text); self.assertNotIn('Authorization', text)
    def test_machine_reference_not_human(self):
        _, metrics = self.call(self.runner(lambda *args: reply())); self.assertFalse(metrics['reference_is_human_gold'])
    def test_default_serial_real_threads(self):
        active = 0; peak = 0; lock = threading.Lock()
        def post(*args):
            nonlocal active, peak
            with lock: active += 1; peak = max(peak, active)
            time.sleep(.01)
            with lock: active -= 1
            return reply()
        runner = self.runner(post)
        with ThreadPoolExecutor(max_workers=3) as pool:
            futures = [pool.submit(runner.call, 's', {'n': n}, dict(DOC, record_id=str(n)), 'test', SCHEMA) for n in range(3)]
            for future in futures: self.assertEqual(future.result()[1]['status'], 'success')
        self.assertEqual(peak, 1)

    def test_multiple_instances_still_serial(self):
        active = 0; peak = 0; lock = threading.Lock()
        def post(*args):
            nonlocal active, peak
            with lock: active += 1; peak = max(peak, active)
            time.sleep(.01)
            with lock: active -= 1
            return reply()
        runners = [self.runner(post) for _ in range(3)]
        with ThreadPoolExecutor(max_workers=3) as pool:
            futures = [pool.submit(r.call, 's', {'n': n}, dict(DOC, record_id=str(n)), 'test', SCHEMA)
                       for n, r in enumerate(runners)]
            for future in futures: self.assertEqual(future.result()[1]['status'], 'success')
        self.assertEqual(peak, 1)

    def test_os_lock_rejects_second_holder_and_releases(self):
        with m.exclusive_proxy_call():
            with self.assertRaises(RuntimeError):
                with m.exclusive_proxy_call(): self.fail('Second holder was admitted')
        with m.exclusive_proxy_call(): pass


if __name__ == '__main__': unittest.main()
