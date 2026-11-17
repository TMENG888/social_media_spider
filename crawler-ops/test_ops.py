import unittest, tempfile, json, time, uuid, threading
from pathlib import Path
from unittest.mock import patch
from datetime import datetime, timezone, timedelta
import adapter, probe, server
from settings import TEMP

def setUpModule():
    TEMP.mkdir(parents=True,exist_ok=True)

class MonitoringTests(unittest.TestCase):
    def test_article_date_failure_is_diagnosable_and_never_reuses_previous_keyword(self):
        dates={'source':'ok','keyword':'previous','latestCollectedPublishedAt':'2026-01-01'}
        value=adapter.article_date_progress('current',dates,None)
        self.assertEqual(value['source'],'unavailable');self.assertEqual(value['errorType'],'DATE_KEYWORD_MISMATCH')
        self.assertIsNone(value['latestCollectedPublishedAt'])
        dates.update(keyword='current')
        value=adapter.article_date_progress('current',dates,{'source':'ok','earliestImportedPublishedAt':'2026-01-01','verifiedPosts':10})
        self.assertEqual(value['latestCollectedPublishedAt'],'2026-01-01');self.assertEqual(value['verifiedPosts'],10)

    def test_real_activity_overrides_stale_heartbeat_without_faking_new_heartbeat(self):
        now=1794294000
        row={'activity':{'foreground':{'at':now-3}},'finishedAt':None}
        self.assertEqual(adapter.with_activity('stale','心跳已过期',row,now),('collecting','采集中'))
        row['activity']={'persistence':{'at':now-3}}
        self.assertEqual(adapter.with_activity('stale','心跳已过期',row,now),('background','后台处理中'))
        row['activity']={'foreground':{'at':now-300}}
        self.assertEqual(adapter.with_activity('stale','心跳已过期',row,now)[0],'stale')
        row['finishedAt']='2026-11-10T06:00:00Z';row['activity']={'foreground':{'at':now-3}}
        self.assertEqual(adapter.with_activity('stale','心跳已过期',row,now)[0],'stale')
        row['state']={'state':'stopped'}
        self.assertEqual(adapter.with_activity('stale','心跳已过期',row,now),('stopped','已停止'))

    def test_heartbeat_distinguishes_rest_from_offline(self):
        now=1794294000
        for raw,expected in [('resting','resting'),('cooldown','cooldown'),('collecting','collecting')]:
            self.assertEqual(adapter.classify({'lastSeenAt':now-2,'state':raw},now,{},True)[0],expected)
        self.assertEqual(adapter.classify({'lastSeenAt':now-31,'state':'collecting'},now,{},True)[0],'stale')
        self.assertEqual(adapter.classify({},now,{},False)[0],'unknown')
        self.assertEqual(adapter.classify({'lastSeenAt':now+60},now,{},True)[0],'unknown')

    def test_day_window_beijing_and_event_dedup(self):
        now=datetime(2026,11,10,0,10,tzinfo=adapter.BJ).timestamp()
        def event(id,offset,**extra):
            return dict(campaign='test',projects=adapter.PROJECTS,readbackVerified=True,eventId=id,committedAt=now+offset,newPosts=3,videoContentWrites=0,**extra)
        valid=event('a',-300)
        rows=adapter.accepted_events([valid,valid,event('yesterday',-700),event('future',60),event('fixture',-1,deploymentTest=True)],'test',now)
        self.assertEqual(len(rows),1)
        self.assertEqual(adapter.output(rows,now)['day'],3)
        self.assertIsNone(adapter.output([],now)['hour'])

    def test_recovery_never_dispatches_with_live_heartbeat(self):
        job=dict(id=str(uuid.uuid4()),machine='work02',platform='xhs',action='recover',createdAt=time.time())
        m=probe.machine('work02')
        r=dict(source='ok',sampledAt=time.time(),holds=[],workers=[dict(computer=m['computer'],worker=probe.worker(m,'xhs'),lastSeenAt=time.time())])
        with patch.object(adapter.relay,'sources',return_value=[('小红书','fake','fake',None)]),patch.object(adapter,'redis_state',return_value=r),patch.object(server,'child') as dispatch,patch.object(server,'audit'):
            server.execute(job,{})
            dispatch.assert_not_called()
            self.assertEqual(job['state'],'blocked')

    def test_recovery_never_dispatches_with_remote_hold(self):
        job=dict(id=str(uuid.uuid4()),machine='work02',platform='xhs',action='recover',createdAt=time.time())
        m=probe.machine('work02');target=m['computer'].upper()+'/'+probe.worker(m,'xhs')
        r=dict(source='ok',sampledAt=time.time(),holds=[{'target':target}],workers=[])
        with patch.object(adapter.relay,'sources',return_value=[('小红书','fake','fake',None)]),patch.object(adapter,'redis_state',return_value=r),patch.object(server,'child') as dispatch,patch.object(server,'audit'):
            server.execute(job,{})
            dispatch.assert_not_called();self.assertEqual(job['state'],'blocked')

    def test_only_xhs_fixed_actions_allowed_and_idempotent(self):
        k=str(uuid.uuid4())
        with self.assertRaises(ValueError):server.submit(dict(machine='work01',platform='douyin',action='recover',idempotencyKey=k))
        with self.assertRaises(ValueError):server.submit(dict(machine='work01',platform='xhs',action='shell',idempotencyKey=k))
        with self.assertRaises(ValueError):server.submit(dict(machine='work01',platform='xhs',action='submit_sms',code='123456',idempotencyKey=k))
        with patch.object(server.POOL,'submit') as dispatch:
            data=dict(machine='work01',platform='xhs',action='recover',idempotencyKey=k)
            first=server.submit(data);second=server.submit(data)
            self.assertEqual(first['id'],second['id']);self.assertEqual(dispatch.call_count,1)
        server.ACTIVE.clear()

    def test_login_rejects_stale_session_and_qr_refresh_during_sms(self):
        s={'sessionId':'fixture','updatedAt':int(time.time()*1000),'phase':'waiting_sms'}
        with patch.object(probe,'session_for',return_value=s):
            r=probe.login_command(dict(machine='work02',platform='xhs',sessionId='wrong',action='refresh_qr',jobId=str(uuid.uuid4())))
            self.assertEqual(r['state'],'blocked')
            r=probe.login_command(dict(machine='work02',platform='xhs',sessionId='fixture',action='refresh_qr',jobId=str(uuid.uuid4())))
            self.assertEqual(r['state'],'blocked')

    def test_login_does_not_overwrite_live_feishu_command(self):
        with tempfile.TemporaryDirectory(dir=TEMP) as tmp:
            root=Path(tmp);bridge=root/'.state/login-bridge';bridge.mkdir(parents=True)
            old={'commandId':str(uuid.uuid4()),'expiresAt':int(time.time()*1000)+30000};file=bridge/'command.json';file.write_text(json.dumps(old))
            s={'sessionId':'fixture','updatedAt':int(time.time()*1000),'phase':'waiting_scan'}
            with patch.object(probe,'session_for',return_value=s),patch.object(probe,'worker_root',return_value=root):
                r=probe.login_command(dict(machine='work02',platform='xhs',sessionId='fixture',action='refresh_qr',jobId=str(uuid.uuid4())))
            self.assertEqual(r['state'],'blocked');self.assertEqual(json.loads(file.read_text()),old)

    def test_qr_rejects_session_change_and_generation_change(self):
        s={'sessionId':'one','generation':2,'phase':'waiting_scan','updatedAt':int(time.time()*1000)}
        with patch.object(probe,'session_for',return_value=s):
            self.assertIn('error',probe.qr(dict(machine='work02',platform='xhs',sessionId='two',generation=2)))
            self.assertIn('error',probe.qr(dict(machine='work02',platform='xhs',sessionId='one',generation=1)))

if __name__=='__main__':unittest.main(verbosity=2)
