import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parent))
from platform_tasks import ReadOnlyRedis, queue_observation, READ_COMMANDS, platform_root
from publish import push_summary, alert_signature, progress_signature, card


class FakeRedis:
    def __init__(self, statuses=None, leases=None):
        self.statuses = statuses if statuses is not None else {'a': 'completed', 'b': 'pending', 'c': 'leased', 'd': 'excluded'}
        self.leases = leases if leases is not None else ['c', '1001000']
        self.calls = []

    def command(self, *parts):
        self.calls.append(parts)
        if parts[0] == 'HVALS':return list(self.statuses.values())
        if parts[0] == 'TIME':return ['1000', '0']
        if parts[0] == 'ZRANGE':return self.leases if parts[1].endswith(':leases') else [key for key,state in self.statuses.items() if state=='pending']
        if parts[0] == 'HGET':
            key, task_id = parts[1:]
            if key.endswith(':statuses'):return self.statuses.get(task_id)
            if key.endswith(':payloads'):return json.dumps({'topic': '专题一', 'keyword': task_id, 'projectName': '项目'})
            if key.endswith(':owners'):return 'worker-01-12345678-1234-1234-1234-123456789abc'
            if key.endswith(':results'):return json.dumps({'status': 'completed'})
            if key.endswith(':attempts'):return '0'
        raise AssertionError(parts)


class PlatformTests(unittest.TestCase):
    def test_repository_platform_directories_and_deployment_override(self):
        self.assertEqual(platform_root('小红书').name, 'xiaohongshu')
        self.assertEqual(platform_root('抖音').name, 'douyin')
        with patch('platform_tasks.Path.exists', return_value=True), patch(
            'platform_tasks.load_json', return_value={'platform_directories': {'小红书': '小红书'}}
        ):
            self.assertEqual(platform_root('小红书').name, '小红书')

    def test_no_change_completion_is_separate_and_terminal(self):
        class NoChangeRedis(FakeRedis):
            def command(self,*parts):
                if parts[0]=='HGET' and parts[1].endswith(':results'):
                    self.calls.append(parts)
                    return json.dumps({'status':'completed_with_skips','disposition':'no_change'})
                return super().command(*parts)
        row=self.observe(NoChangeRedis(statuses={'a':'completed_with_skips'},leases=[]))
        self.assertEqual(row['counts']['completed'],0)
        self.assertEqual(row['counts']['noChangeCompleted'],1)
        self.assertEqual(row['disposedCount'],1)
        row['platform']='小红书'
        self.assertIn('无变化结束 1',push_summary({'platformTasks':[row]},{}))

    def observe(self, fake):
        return queue_observation(ReadOnlyRedis(fake), 'xhs:{production}', 'production', [{'redisTaskId': key} for key in ('a','b','c','d')])

    def test_read_only_guard_rejects_mutation_and_lua(self):
        fake=FakeRedis();c=ReadOnlyRedis(fake)
        for name in ('HSET','DEL','XACK','XREADGROUP','XCLAIM','EVAL','SET'):
            with self.assertRaises(ValueError):c.command(name,'key')
        self.assertEqual(fake.calls,[])

    def test_total_excludes_excluded_and_counts_sum(self):
        fake=FakeRedis();row=self.observe(fake);counts=row['counts']
        self.assertEqual(counts['total'],3);self.assertEqual(counts['excluded'],1)
        self.assertEqual(sum(counts[k] for k in ('pending','leased','completed','failed','unknown')),3)
        self.assertEqual(row['topics']['专题一']['total'],3)
        self.assertTrue(all(call[0] in READ_COMMANDS for call in fake.calls))

    def test_valid_lease_not_online_assertion(self):
        row=self.observe(FakeRedis());self.assertEqual(row['counts']['validLeases'],1)
        self.assertEqual(row['workers'][0]['worker'],'worker-01')
        row['platform']='小红书'
        text=push_summary({'platformTasks':[row]}, {})
        self.assertIn('有效租约不等于确认在线',text)
        self.assertNotIn('小红书/worker-01：采集中',text)

    def test_expired_lease_remains_leased_not_reclaimed(self):
        row=self.observe(FakeRedis(leases=['c','999000']))
        self.assertEqual(row['counts']['leased'],1);self.assertEqual(row['counts']['expiredLeases'],1)
        self.assertEqual(row['counts']['pending'],1)

    def test_missing_lease_not_valid(self):
        row=self.observe(FakeRedis(leases=[]))
        self.assertEqual(row['counts']['missingLeaseEvidence'],1)
        self.assertEqual(row['counts']['validLeases'],0)

    def test_unknown_status_preserved(self):
        row=self.observe(FakeRedis(statuses={'a':'future_status'}))
        self.assertEqual(row['counts']['unknown'],1)
        self.assertEqual(row['counts']['completed'],0)

    def test_skips_are_disposed_but_not_successful(self):
        row=self.observe(FakeRedis(statuses={'a':'completed','b':'completed_with_skips','c':'skipped_unresolved'},leases=[]))
        self.assertEqual(row['counts']['completed'],1)
        self.assertEqual(row['counts']['completed_with_skips'],1)
        self.assertEqual(row['counts']['skipped_unresolved'],1)
        self.assertEqual(row['counts']['unknown'],0)
        self.assertEqual(row['disposedCount'],3)
        text=push_summary({'platformTasks':[{'platform':'小红书',**row}]},{})
        self.assertIn('队列完成 1/3',text)
        self.assertIn('含跳过完成 1',text)
        self.assertIn('整词跳过 1',text)

    def test_absent_queue_unknown_not_zero(self):
        row=self.observe(FakeRedis(statuses={}));self.assertIsNone(row['counts'])
        self.assertEqual(row['source'],'not_published')
        text=push_summary({'platformTasks':[{'platform':'抖音',**row}]},{})
        self.assertIn('抖音：进度未知',text)
        self.assertNotIn('队列完成 0/0',text)

    def test_unmatched_tasks_not_silently_assigned_topic(self):
        row=self.observe(FakeRedis(statuses={'a':'completed','unexpected':'pending'},leases=[]))
        self.assertEqual(row['counts']['total'],2)
        self.assertEqual(row['unmatchedManifestTasks'],0)
        self.assertEqual(row['counts']['pendingNew'],1)

    def test_pending_split_attempts_and_unknown_are_not_conflated(self):
        fake=FakeRedis(statuses={'a':'pending','b':'pending','c':'pending'},leases=[])
        original=fake.command
        def command(*parts):
            if parts[0]=='HGET' and parts[1].endswith(':attempts'):return {'a':'0','b':'2','c':None}[parts[2]]
            return original(*parts)
        fake.command=command
        counts=self.observe(fake)['counts']
        self.assertEqual((counts['pendingNew'],counts['retryPending'],counts['pendingUnclassified']),(1,1,1))
        self.assertEqual(sum(counts[k] for k in ('pendingNew','retryPending','pendingUnclassified')),counts['pending'])

    def test_signatures_ignore_time_and_keywords_but_track_platform_state(self):
        row={'platform':'小红书',**self.observe(FakeRedis())}
        snap={'platformTasks':[row]};changed={'platformTasks':[{**row,'generatedAt':'later'}]}
        self.assertEqual(alert_signature(snap,{}),alert_signature(changed,{}))
        self.assertEqual(progress_signature(snap),progress_signature(changed))
        changed={'platformTasks':[{**row,'source':'unavailable','counts':None,'workers':[]}]}
        self.assertNotEqual(alert_signature(snap,{}),alert_signature(changed,{}))
        changed={'platformTasks':[{**row,'counts':{**row['counts'],'completed':2}}]}
        self.assertNotEqual(progress_signature(snap),progress_signature(changed))

    def test_four_blocks_and_header(self):
        row={'platform':'小红书',**self.observe(FakeRedis())}
        text=push_summary({'platformTasks':[row]}, {'source':'ok','otherPlatforms':[{'platform':'小红书','project':'项目','posts':100,'contentNonempty':70}]})
        for label in ('① 关键词进度','② 机器状态','③ 数据质量与效率','④ 异常与下一步'):self.assertIn(label,text)
        self.assertIn('队列完成 1/3',text);self.assertIn('小红书：入库 100',text)
        self.assertIn('跨平台',card(text)['card']['header']['title']['content'])
        self.assertLess(len(text),12000)


if __name__ == '__main__':unittest.main()
