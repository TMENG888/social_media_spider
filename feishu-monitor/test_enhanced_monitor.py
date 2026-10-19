import sys
import unittest
from pathlib import Path
from datetime import datetime, timezone
sys.path.insert(0,str(Path(__file__).resolve().parent))
from collection_efficiency import measured_growth, sample
from platform_telemetry import machine_states, verified_output
from notification import brief_notification


class EnhancedMonitorTests(unittest.TestCase):
    def test_growth_from_real_snapshot_not_capture_date(self):
        before=sample({'source':'ok','generatedAt':'2026-10-13T03:00:00Z','otherPlatforms':[{'platform':'抖音','project':'p','posts':10,'contentNonempty':4,'latestCollectedAt':'2026-10-13T03:59:00Z'}]})
        after=sample({'source':'ok','generatedAt':'2026-10-13T03:30:00Z','otherPlatforms':[{'platform':'抖音','project':'p','posts':16,'videoContentNonempty':7}]})
        row=measured_growth([before],after)['抖音']
        self.assertEqual((row['netPosts'],row['netVideoContent'],row['netPostsPerHour']),(6,3,12))
        self.assertEqual(row['windowSeconds'],1800)

    def test_sampling_warmup_missing_scope_and_future_not_zero(self):
        current={'at':'2026-10-13T03:30:00Z','platforms':{'小红书':{'projects':['p'],'posts':100,'videoContentNonempty':20}}}
        for history in ([],[{'at':'2026-10-13T04:00:00Z','platforms':current['platforms']}],
                        [{'at':'2026-10-13T03:00:00Z','platforms':{'小红书':{'projects':['q']}}}]):
            self.assertEqual(measured_growth(history,current)['小红书']['source'],'warming_up')
        self.assertIsNone(sample({'source':'unavailable'}))

    def test_negative_delta_is_not_clamped_to_success(self):
        before={'at':'2026-10-13T03:00:00Z','platforms':{'小红书':{'projects':['p'],'posts':10,'videoContentNonempty':4}}}
        after={'at':'2026-10-13T03:30:00Z','platforms':{'小红书':{'projects':['p'],'posts':9,'videoContentNonempty':3}}}
        row=measured_growth([before],after)['小红书']
        self.assertTrue(row['negativeDelta']);self.assertEqual(row['netPosts'],-1)

    def test_heartbeat_rest_and_stale_are_independent_of_lease(self):
        now=datetime(2026,10,13,4,tzinfo=timezone.utc).timestamp()*1000
        records=[{'campaign':'c','computer':'pc','worker':'worker-01','state':'resting','lastSeenAt':'2026-10-13T03:59:58Z','heartbeatIntervalSeconds':3},
                 {'campaign':'c','computer':'pc','worker':'worker-02','state':'collecting','lastSeenAt':'2026-10-13T03:59:00Z'}]
        rows=machine_states(records,'c',now)
        self.assertEqual([w['observation'] for w in rows],['resting','heartbeat_stale'])
        self.assertEqual(rows[0]['evidence'],'independent_supervisor_heartbeat')

    def test_heartbeat_future_campaign_and_tests_excluded(self):
        now=datetime(2026,10,13,4,tzinfo=timezone.utc).timestamp()*1000
        base={'campaign':'c','computer':'pc','worker':'worker-01','state':'collecting','lastSeenAt':'2026-10-13T04:01:00Z'}
        self.assertEqual(machine_states([base],'c',now)[0]['observation'],'clock_skew')
        self.assertEqual(machine_states([{**base,'deploymentTest':True},{**base,'campaign':'other'}],'c',now),[])

    def test_output_requires_readback_and_deduplicates(self):
        now=datetime(2026,10,13,4,tzinfo=timezone.utc).timestamp()*1000
        event={'campaign':'c','eventId':'one','committedAt':'2026-10-13T03:30:00Z','readbackVerified':True,'newPosts':2,'videoContentWrites':1}
        result=verified_output([event,event,{**event,'eventId':'bad','readbackVerified':False},{**event,'eventId':'future','committedAt':'2026-10-13T04:01:00Z'}],'c',now)
        self.assertEqual((result['newPosts'],result['videoContentWrites'],result['verifiedBatches']),(2,1,1))
        self.assertIsNone(verified_output([],'c',now))

    def test_no_lease_is_not_anomaly_even_without_heartbeat(self):
        p={'platform':'抖音','source':'ok','counts':{'total':2,'completed':0,'pending':2,'pendingNew':2,'retryPending':0,'pendingUnclassified':0,'validLeases':0}}
        text,issues=brief_notification({'platformTasks':[p],'sources':{'redis':'ok'}},{'source':'ok'})
        self.assertNotIn('积压但无有效租约',' '.join(issues))
        self.assertIn('心跳未接入',text)
        p['telemetry']={'machines':[{'observation':'resting'}]}
        text,issues=brief_notification({'platformTasks':[p],'sources':{'redis':'ok'}},{'source':'ok'})
        self.assertIn('抖音：1/1 在线（已上报） · 休眠/冷却 1',text)
        self.assertFalse(any('抖音' in issue for issue in issues))

    def test_three_field_quality_and_media_applicability(self):
        row={'platform':'抖音','project':'p','posts':100,'titleNonempty':95,'bodyNonempty':0,'videoContentNonempty':45,'videoEligible':50,'videoEligibleNonempty':45,'coreMissing':10}
        text,issues=brief_notification({'sources':{'redis':'ok'}},{'source':'ok','otherPlatforms':[row]})
        self.assertIn('标题 95.0% · 正文 不适用 · 视频内容 90.0%',text)
        self.assertNotIn('核心字段待核验10条',' '.join(issues))
        self.assertIn('核心字段待核验10条',' '.join(brief_notification({'sources':{'redis':'ok'}},{'source':'ok','otherPlatforms':[row]},include_diagnostics=True)[1]))
        row.update(platform='小红书',bodyNonempty=90)
        text,_=brief_notification({'sources':{'redis':'ok'}},{'source':'ok','otherPlatforms':[row]})
        self.assertIn('正文 90.0%',text)
        row.update(videoEligible=0,videoEligibleNonempty=0)
        text,_=brief_notification({'sources':{'redis':'ok'}},{'source':'ok','otherPlatforms':[row]})
        self.assertIn('视频内容 不适用',text)

    def test_topic_two_action_uses_identity_evidence_not_reset(self):
        s={'sources':{'redis':'ok'},'videoDiagnostics':{'topic2':{'recoverableIdentityCount':150}}}
        text,_=brief_notification(s,{'source':'ok','posts':[{'project':'北京臻澐项目口碑','posts':121,'subtitleNonempty':0}]},include_diagnostics=True)
        self.assertIn('优先精准补采，不整体重置',text)


if __name__=='__main__':unittest.main()
