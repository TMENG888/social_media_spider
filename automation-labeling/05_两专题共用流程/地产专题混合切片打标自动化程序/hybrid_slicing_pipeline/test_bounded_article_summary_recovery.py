import unittest
from unittest.mock import patch
import delivery_v11 as pipeline


class RecoveryRunner:
    def __init__(self, candidate):
        self.candidate = candidate
        self.phases = []

    def call(self, system, payload, doc, phase):
        self.phases.append(phase)
        if phase == '独立文案证据失败有界转写-v11.19':
            return {'summary': None, 'supported': False}, {'status': 'success'}
        if phase == '文章摘要有界压缩恢复-v11.32':
            return {'summary': self.candidate, 'supported': True, 'confidence': .95}, {'status': 'success'}
        if phase == '恢复文章摘要独立证据核验-v11.32':
            return {}, {'status': 'success'}
        raise AssertionError(phase)


class BoundedRecoveryTests(unittest.TestCase):
    source = '臻澐南瞰清河、西望西山，景观资源更突出；海晏则融入人文底蕴深厚的海淀学术氛围，两者所强调的环境特点不同。'

    def run_review(self, candidate, accepted):
        runner = RecoveryRunner(candidate)
        with patch.object(pipeline.prose_review, 'verify', return_value=(accepted, [{'confidence': .95}])):
            result = pipeline.independent_prose_review(
                {'topic': '北京臻澐项目口碑', 'kind': '文章'},
                {'summary': None, 'labels': []}, self.source, '', runner)
        return result, runner

    def test_valid_rephrase_must_pass_independent_review(self):
        candidate = '臻澐强调清河与西山景观，海晏侧重海淀的学术文化环境。'
        (unit, audit, calls, issues), runner = self.run_review(candidate, True)
        self.assertEqual(candidate, unit['summary'])
        self.assertFalse(issues)
        self.assertEqual(3, len(calls))
        self.assertTrue(audit[-1]['passed'])
        self.assertIn('恢复文章摘要独立证据核验-v11.32', runner.phases)

    def test_independent_rejection_stays_empty_and_manual(self):
        (unit, audit, calls, issues), runner = self.run_review(
            '臻澐强调清河与西山景观，海晏侧重海淀的学术文化环境。', False)
        self.assertIsNone(unit['summary'])
        self.assertTrue(issues)
        self.assertFalse(audit[-1]['passed'])

    def test_source_copy_is_not_accepted_despite_confidence(self):
        (unit, audit, calls, issues), runner = self.run_review(self.source, True)
        self.assertIsNone(unit['summary'])
        self.assertTrue(issues)
        self.assertNotIn('恢复文章摘要独立证据核验-v11.32', runner.phases)


if __name__ == '__main__':
    unittest.main()
