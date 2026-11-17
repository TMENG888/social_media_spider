import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import restriction_timeline as rt


class TimelineTests(unittest.TestCase):
    def setUp(self):
        root=Path(__import__('settings').TEMP)/'restriction-tests';root.mkdir(parents=True,exist_ok=True)
        self.tmp=tempfile.TemporaryDirectory(dir=root)
        self.db=Path(self.tmp.name)/'history.sqlite3'
        self.now=1794564000
        self.m=rt.MACHINES[0]

    def tearDown(self):self.tmp.cleanup()

    def raw(self,**kw):
        return dict(dict(machine=self.m['computer'],workerId=rt.worker(self.m,'xhs'),kind='captcha',
                         incidentId='example',startedAt=(self.now-1000)*1000,lastSeenAt=(self.now-900)*1000),**kw)

    def update(self,rows=None,files=None,now=None):
        return rt.update({'小红书':dict(incidents=rows or [],restrictionsSource='ok')},files or {},now or self.now,self.db)

    def query(self,**kw):return rt.query(now=self.now,path=self.db,**kw)

    def test_repeated_incident_is_one_and_resolves(self):
        r=self.raw();self.update([r]);self.update([r]);self.assertEqual(self.query()['total'],1)
        r.update(status='resolved',resolvedAt=(self.now-500)*1000);self.update([r])
        self.assertEqual(self.query()['rows'][0]['status'],'resolved')

    def test_filters_and_interval_before_time_window(self):
        self.update([self.raw(incidentId='old',startedAt=(self.now-90000)*1000),self.raw(incidentId='new')])
        q=self.query();self.assertEqual(q['total'],1);self.assertEqual(q['rows'][0]['intervalSeconds'],89000)
        self.assertEqual(self.query(days=7)['total'],2)
        self.assertEqual(self.query(platform='douyin')['total'],0)
        self.assertEqual(self.query(machine='work04')['total'],0)

    def test_worker_identity_and_test_incidents(self):
        self.update([self.raw(workerId='wrong'),self.raw(test=True),self.raw(deploymentTest=True),self.raw(kind='database')])
        self.assertEqual(self.query()['total'],0)

    def session(self,**kw):
        return dict(dict(platform='xhs',machine=self.m['label'],sessionId='s1',phase='waiting_scan',updatedAt=self.now,proof=False),**kw)

    def test_qr_refresh_sms_and_proof(self):
        def send(s):self.update(files={self.m['label']:dict(sessions=[s])})
        s=self.session();send(s);send(dict(s,generation=99));self.assertEqual(self.query()['total'],1)
        send(dict(s,phase='waiting_sms'));self.assertEqual(self.query()['rows'][0]['kind'],'login')
        self.assertEqual(self.query()['rows'][0]['verificationSteps'][0]['kind'],'sms')
        send(dict(s,phase='verified',verifiedAt=self.now,proof=False));self.assertIsNone(self.query()['rows'][0]['resolved'])
        send(dict(s,phase='verified',verifiedAt=self.now,proof=True));self.assertEqual(self.query()['rows'][0]['status'],'resolved')
        self.assertEqual(self.query()['total'],1)

    def test_session_enriches_incident_without_duplicate(self):
        r=self.raw(lastSeenAt=self.now*1000)
        self.update([r],{self.m['label']:dict(sessions=[self.session(phase='manual_captcha',challengeType='slider')])})
        self.assertEqual(self.query()['total'],1);self.assertEqual(self.query()['rows'][0]['kind'],'captcha')
        self.assertEqual(self.query()['rows'][0]['verificationSteps'][0]['kind'],'slider')
        self.update([r]);self.assertEqual(self.query()['rows'][0]['verificationSteps'][0]['kind'],'slider')

    def test_stale_session_and_completed_session_not_backdated(self):
        self.update(files={self.m['label']:dict(sessions=[self.session(updatedAt=self.now-60)])})
        self.update(files={self.m['label']:dict(sessions=[self.session(phase='verified',proof=True,verifiedAt=self.now-100)])})
        self.assertEqual(self.query()['total'],0)

    def test_rate_log_dedup_and_expiry_is_not_proof(self):
        r=dict(id='rate-1',platform='xhs',machine=self.m['label'],kind='security',started=self.now-2000,
               last_seen=self.now-2000,cooldown=self.now-1000,precision='recorded',source='cooldown_log')
        files={self.m['label']:dict(records=[r,r])};self.update(files=files)
        self.assertEqual(self.query()['total'],1);self.assertEqual(self.query()['rows'][0]['status'],'unconfirmed')

    def test_same_cooldown_in_redis_and_log_counts_once(self):
        raw=self.raw(kind='security',cooldownUntil=(self.now+1000)*1000)
        log=dict(id='rate-log',platform='xhs',machine=self.m['label'],kind='security',started=self.now-998,
                 last_seen=self.now-998,cooldown=self.now+1000,precision='recorded',source='cooldown_log',keyword='住宅')
        self.update([raw],{self.m['label']:dict(records=[log])})
        self.assertEqual(self.query()['total'],1);self.assertEqual(self.query()['rows'][0]['keyword'],'住宅')

    def test_log_reader_ignores_transport_errors_and_read_observations(self):
        root=Path(self.tmp.name)/'worker';(root/'runs').mkdir(parents=True)
        day=rt.datetime.fromtimestamp(self.now,rt.BJ).strftime('%Y-%m-%d')
        base=dict(at=self.now,machine=self.m['computer'],workerId=rt.worker(self.m,'xhs'),
                  protection=dict(active=True,untilMs=(self.now+1000)*1000))
        rows=[dict(base,event='operation_failed',stage='record_rate_limit'),
              dict(base,event='protection_active',stage='read_scoped_cooldown'),
              dict(base,event='operation_ok',stage='record_rate_limit',password='SECRET',code='123456')]
        (root/'runs'/f'cooldown-diagnostics-{day}.jsonl').write_text('\n'.join(json.dumps(r) for r in rows),encoding='utf-8')
        with patch.object(rt,'worker_root',return_value=root):result=rt.collect_files(self.m['label'],self.now)
        self.assertEqual(len(result['records']),1)
        self.assertNotIn('SECRET',json.dumps(result));self.assertNotIn('123456',json.dumps(result))

    def test_validation_and_no_unknown_zero_interval(self):
        self.update([self.raw()]);self.assertIsNone(self.query()['rows'][0]['intervalSeconds'])
        for k,v in [('days',30),('machine','host'),('platform','bad'),('page',0)]:
            with self.assertRaises(ValueError):self.query(**{k:v})


if __name__=='__main__':unittest.main()
