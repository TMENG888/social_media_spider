import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
COMMON = Path(os.environ.get('XHS_TEST_COMMON', str(HERE.parent)))


class CycleIntegrationTests(unittest.TestCase):
    def run_case(self, scenario, single=False):
        root = Path(tempfile.mkdtemp(prefix='powershell-cycle-', dir=os.environ['TEMP']))
        common = root / 'common'
        worker = root / 'worker-02'
        for directory in (common / 'src', worker / 'tasks', worker / '.state', worker / 'runs'):
            directory.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(COMMON / 'run-distributed-worker.ps1', common / 'run-distributed-worker.ps1')
        shutil.copyfile(COMMON / 'src/runtime-stop.mjs', common / 'src/runtime-stop.mjs')
        shutil.copyfile(HERE / 'mock-run-worker.mjs', common / 'src/run-worker.mjs')
        shutil.copyfile(HERE / 'mock-monitor.ps1', common / 'monitor-supervisor.ps1')
        for name in ('redis-auth-check.mjs', 'remote-stop-control.mjs', 'cooldown-control.mjs'):
            shutil.copyfile(HERE / 'noop.mjs', common / 'src' / name)
        (common / 'redis-config.json').write_text(json.dumps({'url': 'redis://127.0.0.1:1/0', 'username': 'fixture'}), encoding='utf-8')
        (worker / 'tasks/task-queue.json').write_text(json.dumps({'workerId': 'worker-02',
            'stateRoot': '../.state', 'runsRoot': '../runs', 'tasks': []}), encoding='utf-8')
        env = dict(os.environ, REDIS_PASSWORD='fixture-not-a-secret', MYSQL_USER='fixture',
                   MYSQL_PASSWORD='fixture-not-a-secret', XHS_TEST_SCENARIO=scenario)
        args = ['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
                str(common / 'run-distributed-worker.ps1'), '-WorkerRoot', str(worker),
                '-CycleRunMinMinutes', '1', '-CycleRunMaxMinutes', '1',
                '-CycleRestMinMinutes', '1', '-CycleRestMaxMinutes', '1']
        if single:
            args += ['-SingleCycle', '-MaxRuntimeMinutes', '1']
        result = subprocess.run(args, capture_output=True, env=env, timeout=25)
        (root / 'stdout.log').write_bytes(result.stdout)
        (root / 'stderr.log').write_bytes(result.stderr)
        count_file = worker / '.state/fixture-round-count.json'
        count = json.loads(count_file.read_text()) if count_file.exists() else 0
        return result, worker, count

    def test_real_powershell_wrapper_completes_two_rounds_after_timeout(self):
        result, worker, count = self.run_case('timeout')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(count, 2)
        self.assertFalse((worker / '.state/stop.requested').exists())
        self.assertIn(b'owned_runtime_stop_consumed', result.stdout)

    def test_no_timeout_marker_does_not_block_next_round(self):
        result, worker, count = self.run_case('no-timeout')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(count, 2)

    def test_manual_stop_written_during_rest_prevents_round_two(self):
        result, worker, count = self.run_case('manual-during-rest')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(count, 1)
        self.assertEqual((worker / '.state/stop.requested').read_text(), 'manual stop during rest')

    def test_manual_stop_replacing_timeout_is_not_deleted(self):
        result, worker, count = self.run_case('manual-before-rest')
        self.assertEqual(count, 1)
        self.assertEqual((worker / '.state/stop.requested').read_text(), 'manual stop fixture')

    def test_unverified_legacy_timeout_requires_manual_confirmation(self):
        result, worker, count = self.run_case('legacy-stop')
        self.assertEqual(count, 1)
        self.assertTrue((worker / '.state/stop.requested').read_text().startswith('runtime limit'))

    def test_lease_failure_prevents_resume_and_retains_marker(self):
        result, worker, count = self.run_case('lease-failed')
        self.assertEqual(result.returncode, 5)
        self.assertEqual(count, 1)
        self.assertTrue((worker / '.state/stop.requested').exists())

    def test_import_failure_prevents_resume_and_retains_marker(self):
        result, worker, count = self.run_case('import-failed')
        self.assertEqual(result.returncode, 1)
        self.assertEqual(count, 1)
        self.assertTrue((worker / '.state/stop.requested').exists())

    def test_single_cycle_success_consumes_only_its_own_marker(self):
        result, worker, count = self.run_case('timeout', single=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(count, 1)
        self.assertFalse((worker / '.state/stop.requested').exists())


if __name__ == '__main__':
    unittest.main(verbosity=2)
