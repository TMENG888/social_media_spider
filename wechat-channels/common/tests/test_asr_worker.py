import importlib.util
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


SOURCE = Path(__file__).parents[1] / "src" / "asr-worker.py"
SPEC = importlib.util.spec_from_file_location("channels_asr_worker", SOURCE)
worker = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = worker
SPEC.loader.exec_module(worker)


class ParentWatchdogTests(unittest.TestCase):
    def test_windows_liveness_probe_never_uses_os_kill(self):
        with patch.object(worker.os, "name", "nt"), patch.object(
            worker, "_windows_process_is_alive", return_value=True
        ) as windows_probe, patch.object(worker.os, "kill") as os_kill:
            self.assertTrue(worker.process_is_alive(1234))
        windows_probe.assert_called_once_with(1234)
        os_kill.assert_not_called()

    def test_non_windows_liveness_probe_uses_signal_zero(self):
        with patch.object(worker.os, "name", "posix"), patch.object(
            worker.os, "kill"
        ) as os_kill:
            self.assertTrue(worker.process_is_alive(1234))
        os_kill.assert_called_once_with(1234, 0)

    def test_watchdog_shuts_down_only_after_parent_exits(self):
        server = Mock()
        with patch.object(worker.time, "sleep"), patch.object(
            worker, "process_is_alive", side_effect=[True, False]
        ) as alive:
            worker.parent_watchdog(server, 1234)
        self.assertEqual(alive.call_count, 2)
        server.shutdown.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
