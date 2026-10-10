import ast
import json
import unittest
from pathlib import Path

COMMON = Path(__file__).resolve().parents[1]


class SmallModelDefaultsTests(unittest.TestCase):
    def test_shared_config_uses_small_cpu_int8(self):
        config = json.loads((COMMON / 'collector_config.json').read_text(encoding='utf-8-sig'))
        self.assertEqual(config['client_asr_model'], 'small')
        self.assertEqual(config['client_asr_device'], 'cpu')
        self.assertEqual(config['client_asr_compute_type'], 'int8')

    def test_python_model_fallbacks_use_small(self):
        for name in ('channels_pc_collector.py', 'asr-worker.py', 'redis_task_queue.py'):
            tree = ast.parse((COMMON / 'src' / name).read_text(encoding='utf-8-sig'))
            defaults = [node.args[1].value for node in ast.walk(tree)
                        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                        and node.func.attr == 'get' and len(node.args) >= 2
                        and isinstance(node.args[0], ast.Constant)
                        and node.args[0].value == 'client_asr_model'
                        and isinstance(node.args[1], ast.Constant)]
            self.assertTrue(defaults, name)
            self.assertTrue(all(value == 'small' for value in defaults), (name, defaults))

    def test_browser_default_uses_small(self):
        source = (COMMON / 'src' / 'channels_browser_enricher.mjs').read_text(encoding='utf-8')
        self.assertIn('process.env.WECHAT_ASR_MODEL || "small"', source)


if __name__ == '__main__':
    unittest.main()
