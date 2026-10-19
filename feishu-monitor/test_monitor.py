import unittest
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from collect import progress
from publish import summary,push_summary,alert_signature,card,should_send,progress_signature
from production_metrics import hourly_metrics,read_outputs
from worker_visibility import reportable_worker,reporting_snapshot
import json
from datetime import datetime,timezone
from datetime import timedelta
from worker_metrics import worker_states,phase_metrics,progress_rate,stamp
class MonitorTests(unittest.TestCase):
    def test_test_worker_prefix_is_narrow(self):
        for name in ('worker-local-test','worker-local-test-17','worker-local-test-22','worker-local-test-27'):
            self.assertFalse(reportable_worker(name))
        for name in ('worker-01','worker-02','worker-03','worker-04','worker-local-testing'):
            self.assertTrue(reportable_worker(name))
    def test_test_registry_and_logs_do_not_create_workers(self):
        now,r,cfg=self.worker_fixture()
        test={**r,'worker':'worker-local-test-27','consumer':'test'}
        log={'worker':'worker-local-test','computer':'PC','timestamp':now.isoformat()}
        workers=worker_states({'c':r,'test':test},{},[('1',log)],{},now,cfg,'g')
        self.assertEqual([w['worker'] for w in workers],['worker-02'])
    def test_test_workers_hidden_from_all_presentations_and_alerts(self):
        formal={'worker':'worker-02','computer':'PC','observation':'stopped'}
        test={'worker':'worker-local-test-22','computer':'PC','observation':'executing'}
        base={'sources':{'redis':'ok'},'workers':[formal],'videos':{'checkpointStates':{'retry_pending':10}}}
        mixed={**base,'workers':[formal,test],'productionOutputs':{'latest':[test],'perWorker':[test]},
               'recentErrors':[{'worker':'PC/worker-local-test-22'}]}
        db={'source':'ok','posts':[{'project':'项目','posts':100,'subtitleNonempty':80}]}
        for render in (summary,push_summary):
            text=render(mixed,db)
            self.assertNotIn('worker-local-test',text)
            if render is summary:self.assertIn('worker-02',text)
            else:self.assertNotIn('历史停止记录',text)
            self.assertIn('入库100',text.replace(' ',''))
        self.assertEqual(alert_signature(base,db),alert_signature(mixed,db))
        self.assertEqual(progress_signature(base),progress_signature(mixed))
        visible=reporting_snapshot(mixed)
        self.assertEqual(visible['videos']['checkpointStates']['retry_pending'],10)
        self.assertEqual(visible['recentErrors'],[])
        self.assertEqual(mixed['workers'],[formal,test])
    def test_output_only_test_worker_cannot_reappear_but_real_totals_remain(self):
        now=datetime(2026,10,12,12,tzinfo=timezone.utc)
        event={'eventId':'e','worker':'worker-local-test-22','computer':'PC','generation':'g',
               'committedAt':now.isoformat(),'readbackVerified':True,
               'items':[{'table':'ods_social_media_post','platform':'微信视频号','operation':'update','types':['subtitle']}]}
        latest={'worker':'worker-local-test-22','computer':'PC','generation':'g'}
        class FakeRedis:
            def command(self,*args):
                if args[0]=='TYPE':return 'stream'
                if args[0]=='XRANGE':return [('1-0',['record',json.dumps(event)])]
                if args[0]=='HGETALL':return ['test',json.dumps(latest)]
                raise AssertionError(args)
        outputs=read_outputs(FakeRedis(),'p','g',now)
        self.assertEqual(outputs['latest'],[])
        self.assertEqual(outputs['perWorker'],[])
        self.assertEqual(outputs['hourly']['subtitleWrites'],1)
    def test_test_phases_do_not_affect_production_machine_efficiency(self):
        now=datetime(2026,10,12,12,tzinfo=timezone.utc)
        log={'worker':'worker-local-test-17','timestamp':now.isoformat(),'event':'worker_output',
             'message':'{"event":"persistent_asr_request_complete","elapsed_seconds":38}'}
        self.assertEqual(phase_metrics([('1',log)],now)['asrSamples'],0)
    def test_deferred_is_not_final(self):
        tasks=[{'topic':'topic1','task_id':'a','keyword':'A'}]
        topics,_=progress(tasks,{'a':{'status':'completed_with_deferred_retries','checkpointGuard':{'ok':True}}},{'a':{'retry_pending':2}})
        self.assertEqual(topics['topic1']['partial'],1)
    def test_checkpoint_blocks_completed(self):
        tasks=[{'topic':'topic1','task_id':'a','keyword':'A'}]
        topics,_=progress(tasks,{'a':{'status':'completed','checkpointGuard':{'ok':True}}},{'a':{'dead_letter':1}})
        self.assertEqual(topics['topic1']['confirmed'],0)
    def test_mostly_completed_keeps_unresolved(self):
        tasks=[{'topic':'topic1','task_id':'a','keyword':'A'}]
        topics,rows=progress(tasks,{'a':{'status':'completed_with_deferred_retries','checkpointGuard':{'ok':True}}},{'a':{'completed':8,'retry_pending':2}})
        self.assertEqual(topics['topic1']['mostly_completed'],1)
        self.assertEqual(rows[0]['unresolvedVideos'],2)
        self.assertEqual(topics['topic1']['confirmed'],0)
    def test_running_sample_not_mostly_complete(self):
        tasks=[{'topic':'topic1','task_id':'a','keyword':'A'}]
        topics,_=progress(tasks,{'a':{'status':'running'}},{'a':{'completed':8,'retry_pending':1}})
        self.assertEqual(topics['topic1']['partial'],1)
    def test_failed_search_without_video_is_uncollected(self):
        tasks=[{'topic':'topic1','task_id':'a','keyword':'A'}]
        topics,rows=progress(tasks,{'a':{'status':'retry_pending'}},{})
        self.assertEqual(topics['topic1']['uncollected'],1)
        self.assertTrue(rows[0]['attempted'])
    def test_categories_sum_to_plan(self):
        tasks=[{'topic':'topic1','task_id':'a','keyword':'A'},{'topic':'topic1','task_id':'b','keyword':'B'}]
        topics,_=progress(tasks,{},{});p=topics['topic1']
        self.assertEqual(sum(p[k] for k in ('confirmed','mostly_completed','partial','uncollected')),p['planned'])
    def test_unknown_not_zero(self):
        self.assertIn('不是零任务',summary({'sources':{'redis':'unavailable'}},{'source':'unavailable'}))
    def test_card_plain_text(self):
        self.assertEqual(card('<script>x</script>')['card']['elements'][0]['text']['tag'],'plain_text')
    def test_push_short_sections_and_no_wrong_sync_inference(self):
        s={'sources':{'redis':'ok'},'workers':[{'worker':'worker-02','observation':'stopped','registrationObserved':True}],
           'progress':{'topic1':{'planned':223,'confirmed':4,'mostly_completed':10,'partial':198,'uncollected':11}}}
        text=push_summary(s,{'source':'ok'})
        self.assertLess(len(text),1100)
        for label in ('① 关键词进度','② 机器状态','③ 数据质量与效率','④ 异常与下一步'):self.assertIn(label,text)
        self.assertNotIn('历史停止记录',text);self.assertNotIn('需同步新代码',text)
        self.assertIn('耗时/成本未知',text)
    def test_push_unavailable_database_not_empty(self):
        text=push_summary({'sources':{'redis':'unavailable'}},{'source':'unavailable'})
        self.assertIn('未知',text);self.assertNotIn('入库0',text)
    def test_card_section_dividers(self):
        self.assertEqual(card('a\n\nb')['card']['elements'][1]['tag'],'hr')
    def test_heartbeat_interruption_display_stop_not_safe_exit(self):
        now,r,cfg=self.worker_fixture(seconds=40)
        worker=worker_states({'c':r},{},[],{},now,cfg,'g')[0]
        text=push_summary({'workers':[worker]}, {})
        self.assertIn('worker-02：心跳过期，运行待确认',text)
        self.assertIn('不代表已安全退出或保存断点',text)
        self.assertEqual(worker['observation'],'heartbeat_stale')
        self.assertIn('已停止（心跳中断',summary({'workers':[worker]},{}))
    def test_never_registered_business_stop_not_falsely_safe_stopped(self):
        text=push_summary({'workers':[{'worker':'worker-01','observation':'registration_unobserved'}]}, {})
        self.assertIn('worker-01：无注册心跳，运行待确认',text)
        self.assertNotIn('未上报心跳',text)
        self.assertNotIn('worker-01：已安全停止',text)
        self.assertNotIn('心跳未观察到',text)
    def test_pending_retry_details_retained_outside_short_notification(self):
        worker={'worker':'worker-01','observation':'registration_unobserved','pendingLeaseCount':535,'pendingVideoRetryTasks':535,
                'leases':[{'messageId':'abc','lastTouchAt':'2026-10-12T14:30:00+08:00'}]}
        text=push_summary({'workers':[worker]}, {})
        self.assertNotIn('遗留租约',text);self.assertNotIn('待补采任务535条',text)
        self.assertNotIn('最近触达',text)
        visible=reporting_snapshot({'workers':[worker]})
        self.assertEqual(visible['workers'][0]['leases'][0]['lastTouchAt'],'2026-10-12T14:30:00+08:00')
        self.assertEqual(worker['pendingLeaseCount'],535)
    def test_primary_pending_not_mislabeled_video_retry(self):
        now,r,cfg=self.worker_fixture('stopped',3600,False)
        pending={'c':[{'stream':'tasks','messageId':'1','leaseIdleMs':400000}]}
        worker=worker_states({'c':r},{},[],pending,now,cfg,'g')[0]
        text=push_summary({'workers':[worker]}, {})
        self.assertEqual(worker['pendingKeywordTasks'],1);self.assertNotIn('待补采任务1条',text)
    def test_pending_counts_all_messages_not_top_three(self):
        now,r,cfg=self.worker_fixture()
        own=[{'stream':'video-retry','messageId':str(i),'leaseIdleMs':400000+i} for i in range(8)]
        own.append({'stream':'tasks','messageId':'primary','leaseIdleMs':400000})
        worker=worker_states({'c':r},{},[],{'c':own},now,cfg,'g')[0]
        self.assertEqual(len(worker['leases']),3)
        self.assertEqual(worker['pendingKeywordTasks'],1)
        self.assertEqual(worker['pendingVideoRetryTasks'],8)
    def test_fresh_heartbeat_still_executing(self):
        now,r,cfg=self.worker_fixture(seconds=3)
        worker=worker_states({'c':r},{},[],{},now,cfg,'g')[0]
        self.assertIn('视频号：当前在线 1台 · 执行 1节点',push_summary({'workers':[worker]},{}))
        self.assertIn('在线执行',summary({'workers':[worker]},{}))
    def test_alerts_ignore_counter_change(self):
        self.assertEqual(alert_signature({'sources':{'redis':'ok'},'videos':{'count':1}},{'source':'ok'}),alert_signature({'sources':{'redis':'ok'},'videos':{'count':2}},{'source':'ok'}))
    def test_output_metrics_use_commit_time_and_unique_event(self):
        now=datetime(2026,10,12,12,tzinfo=timezone.utc)
        event={'eventId':'e1','generation':'g1','committedAt':'2026-10-12T11:30:00Z','readbackVerified':True,'items':[{'table':'ods_social_media_post','platform':'微信视频号','operation':'insert','types':['metadata','subtitle']}]}
        old={**event,'eventId':'old','committedAt':'2026-10-12T08:00:00Z'}
        wrong={**event,'eventId':'wrong','generation':'g0'}
        unverified={**event,'eventId':'unverified','readbackVerified':False}
        r=hourly_metrics([event,event,old,wrong,unverified],now,'g1')
        self.assertEqual(r['newVideos'],1);self.assertEqual(r['subtitleWrites'],1)
        self.assertIsNone(r['qualifiedSubtitleWrites'])
    def worker_fixture(self,status='running',seconds=3,task=True):
        now=datetime(2026,10,12,12,tzinfo=timezone.utc)
        r={'computer':'PC','worker':'worker-02','consumer':'c','lastSeenAt':(now-timedelta(seconds=seconds)).isoformat(),'controlStatus':status,'taskId':'t' if task else None,'keyword':'K' if task else None,'taskStatus':'running' if task else 'stopped'}
        return now,r,{'expected_workers':['worker-02']}
    def test_stopped_pending_not_executing(self):
        now,r,cfg=self.worker_fixture('stopped',3600,False)
        w=worker_states({'c':r},{'c':{'status':'stopped','observedAt':r['lastSeenAt']}},[],{'c':[{'stream':'tasks','messageId':'1','leaseIdleMs':400000}]},now,cfg,'g')[0]
        self.assertEqual(w['observation'],'stopped');self.assertIsNone(w['currentKeyword'])
        self.assertTrue(w['leases'][0]['reclaimEligible'])
    def test_new_consumer_supersedes_old_stop(self):
        now,r,cfg=self.worker_fixture()
        old={**r,'consumer':'old','controlStatus':'stopped','lastSeenAt':(now-timedelta(hours=1)).isoformat()}
        w=worker_states({'old':old,'c':r},{},[],{},now,cfg,'g')[0]
        self.assertEqual(w['observation'],'executing');self.assertEqual(w['consumer'],'c')
    def test_old_generation_registry_excluded(self):
        now,r,cfg=self.worker_fixture();r['generation']='old'
        w=worker_states({'c':r},{},[],{},now,cfg,'g')[0]
        self.assertFalse(w['registrationObserved'])
    def test_stale_heartbeat_not_current_keyword(self):
        now,r,cfg=self.worker_fixture(seconds=40)
        w=worker_states({'c':r},{},[],{},now,cfg,'g')[0]
        self.assertEqual(w['observation'],'heartbeat_stale');self.assertIsNone(w['currentKeyword'])
    def test_no_log_not_offline(self):
        now,r,cfg=self.worker_fixture(task=False)
        w=worker_states({'c':r},{},[],{},now,cfg,'g')[0]
        self.assertEqual(w['observation'],'online_waiting')
    def test_lease_uses_published_threshold(self):
        now,r,cfg=self.worker_fixture();r['leaseReclaimSeconds']=900
        w=worker_states({'c':r},{},[],{'c':[{'stream':'tasks','messageId':'1','leaseIdleMs':400000}]},now,cfg,'g')[0]
        self.assertFalse(w['leases'][0]['reclaimEligible'])
    def test_naive_timestamp_beijing(self):
        self.assertEqual(stamp('2026-10-12T16:00:00').hour,8)
    def test_phase_asr_not_db_output(self):
        now=datetime(2026,10,12,12,tzinfo=timezone.utc)
        row={'consumer':'c','worker':'w','timestamp':now.isoformat(),'event':'worker_output','message':'{"event":"persistent_asr_request_complete","id":"a","elapsed_seconds":124.77,"duration_seconds":400,"quality":{"accepted":true}}'}
        r=phase_metrics([('1',row),('2',row)],now)
        self.assertEqual(r['asrSamples'],1);self.assertEqual(r['averageAsrSeconds'],124.77)
    def test_eta_requires_active_and_samples(self):
        now=datetime(2026,10,12,12,tzinfo=timezone.utc)
        snap={'generation':'g','videos':{'checkpointStates':{'completed':110,'retry_pending':100}}}
        history=[{'at':(now-timedelta(minutes=30)).isoformat(),'generation':'g','completed':100}]
        r,_=progress_rate(history,snap,now,[{'observation':'executing'}],{})
        self.assertEqual(r['netCompletedPerHour'],20);self.assertEqual(r['knownBacklogEtaHours'],[3.5,7.5])
        r,_=progress_rate(history,snap,now,[{'observation':'stopped'}],{})
        self.assertIsNone(r['knownBacklogEtaHours'])
    def test_reset_does_not_create_rate(self):
        now=datetime(2026,10,12,12,tzinfo=timezone.utc)
        snap={'generation':'new','videos':{'checkpointStates':{'completed':1}}}
        r,_=progress_rate([{'at':(now-timedelta(minutes=30)).isoformat(),'generation':'old','completed':100}],snap,now,[{'observation':'executing'}],{})
        self.assertIsNone(r['netCompletedPerHour'])
    def test_updated_does_not_mean_no_output(self):
        text=summary({'workers':[{'worker':'w','registrationObserved':True,'observation':'stopped'}]},{})
        self.assertNotIn('需同步新代码',text);self.assertIn('已安全停止',text)
    def test_alert_changes_on_machine_transition(self):
        a={'sources':{'redis':'ok'},'workers':[{'worker':'w','computer':'PC','observation':'executing'}]}
        b={**a,'workers':[{'worker':'w','computer':'PC','observation':'stopped'}]}
        self.assertNotEqual(alert_signature(a,{'source':'ok'}),alert_signature(b,{'source':'ok'}))
    def test_watch_unchanged_silent(self):
        s={'sources':{'redis':'ok'}};db={'source':'ok'}
        p={'sourceSignature':alert_signature(s,db),'progressSignature':progress_signature(s),'deliveredAt':1}
        self.assertFalse(should_send(p,s,db,1000,watch=True))
    def test_watch_progress_batched(self):
        s={'sources':{'redis':'ok'},'videos':{'checkpointStates':{'completed':10}}};db={'source':'ok'}
        p={'sourceSignature':alert_signature(s,db),'progressSignature':'old','deliveredAt':1}
        self.assertFalse(should_send(p,s,db,100,watch=True))
        self.assertTrue(should_send(p,s,db,1000,watch=True))
if __name__=='__main__':unittest.main()
