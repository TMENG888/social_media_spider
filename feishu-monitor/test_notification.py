import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from notification import brief_notification, SECTION_TITLES, video_progress_line, platform_progress_line, retry_task_issues
from publish import card


class NotificationTests(unittest.TestCase):
    def test_unreported_configured_slots_hidden_without_losing_activity(self):
        snapshot,db=self.fixture()
        for platform in snapshot['platformTasks']:
            platform['configuredWorkers']=[f'worker-0{i}' for i in range(1,6)]
            platform['telemetry']={'machines':[{'worker':'worker-01','observation':'executing'}]}
            platform['counts']['validLeases']=1
            platform['activeLeaseActivity']={'new':0,'retry':1,'unknown':0}
        text,_=brief_notification(snapshot,db)
        self.assertNotIn('配置槽位',text)
        for name in ('小红书','抖音'):
            self.assertIn(name+'：1/1 在线（已上报） · 租约：新任务 0 · 重试 1',text)
        self.assertEqual(len(snapshot['platformTasks'][0]['configuredWorkers']),5)

    def test_machine_block_distinguishes_new_and_retry_work(self):
        snapshot,db=self.fixture()
        for worker,kind in zip(snapshot['workers'],('new','retry','unknown')):
            worker.update(computer=worker['worker'],taskActivity=kind)
        text,_=brief_notification(snapshot,db)
        self.assertIn('执行 3节点（新任务 1 · 重试 1 · 类型未确认 1）',text)

    def test_stopped_history_is_not_current_machine_failure(self):
        snapshot,db=self.fixture()
        for i,worker in enumerate(snapshot['workers']):worker['computer']=f'pc-{i}'
        snapshot['workers'] += [
            {'computer':'pc-0','worker':'worker-04','observation':'stopped'},
            {'computer':'old-pc','worker':'worker-01','observation':'stopped'}]
        text,issues=brief_notification(snapshot,db)
        self.assertIn('视频号：当前在线 3台 · 执行 3节点',text)
        self.assertNotIn('历史停止记录',text)
        self.assertNotIn('已安全停止',text)
        self.assertNotIn('3/5 在线',text)
        self.assertFalse(any('视频号机器异常' in issue for issue in issues))

    def test_multiple_slots_count_as_one_machine_and_stale_is_uncertain(self):
        snapshot,db=self.fixture()
        for worker in snapshot['workers']:worker['computer']='same-pc'
        snapshot['workers'].append({'computer':'other-pc','worker':'worker-04','observation':'heartbeat_stale'})
        text,issues=brief_notification(snapshot,db)
        self.assertIn('当前在线 1台 · 执行 3节点',text)
        self.assertIn('other-pc/worker-04：心跳过期，运行待确认',text)
        self.assertFalse(any('视频号机器异常' in issue for issue in issues))
        self.assertTrue(any('视频号机器异常' in issue for issue in brief_notification(snapshot,db,include_diagnostics=True)[1]))

    def test_video_no_change_detail_hidden_and_completion_scope_disclosed(self):
        snapshot,db=self.fixture();snapshot['videos']['noChangeCompleted']=7
        text,_=brief_notification(snapshot,db)
        self.assertNotIn('无变化结束',text)
        self.assertIn('完成含跳过结案，非全量采齐',text)
        self.assertEqual(snapshot['videos']['noChangeCompleted'],7)

    def test_three_video_buckets_include_work_in_progress_and_pending_import(self):
        snapshot={'keywordQueueCounts':{'states':{'completed':37,'running':3,'recollect_pending':236},
                                      'completedPendingImport':4,'resetOnceCompleted':4}}
        line=video_progress_line(snapshot,{'planned':276,'confirmed':3})
        self.assertEqual(line,'视频号：完成✅ 33/276 · 重试 243 · 待领 0')
        self.assertEqual(snapshot['keywordQueueCounts']['states']['completed'],37)
        self.assertNotIn('重采结案',line)

    def test_three_platform_buckets_merge_skips_without_double_counting_subsets(self):
        platform={'platform':'抖音','counts':{'total':279,'completed':14,'completed_with_skips':1,
            'skipped_unresolved':0,'pendingNew':256,'retryPending':8,'leased':0,'failed':0,
            'noChangeCompleted':1},'resetOnceCompleted':1}
        self.assertEqual(platform_progress_line(platform),'抖音：完成✅ 15/279 · 重试 8 · 待领 256')
        platform['completedPendingImport']=1
        self.assertEqual(platform_progress_line(platform),'抖音：完成✅ 14/279 · 重试 9 · 待领 256')

    def test_leased_and_failed_are_unfinished_not_completed(self):
        platform={'platform':'小红书','counts':{'total':7,'completed':1,'pendingNew':1,
            'retryPending':2,'leased':1,'failed':2}}
        self.assertEqual(platform_progress_line(platform),'小红书：完成✅ 1/7 · 重试 5 · 待领 1')

    def test_unclassified_or_missing_states_do_not_fabricate_zero(self):
        line=platform_progress_line({'platform':'小红书','counts':{'total':3,'completed':0,
            'pendingNew':1,'retryPending':1,'pendingUnclassified':1}})
        self.assertEqual(line,'小红书：完成✅ 0/3 · 重试 未确认 · 待领 未确认')
        line=video_progress_line({'keywordQueueCounts':{'states':{'completed':1,'future_state':2}}},
                                 {'planned':3,'confirmed':0})
        self.assertIn('重试 未确认',line)

    def fixture(self):
        s={'generatedAt':'2026-10-13T11:20:00+08:00','sources':{'redis':'ok'},
           'progress':{'topic1':{'planned':223,'confirmed':4,'mostly_completed':10,'partial':198,'uncollected':11},
                       'topic2':{'planned':53,'confirmed':0,'mostly_completed':0,'partial':2,'uncollected':51}},
           'workers':[{'worker':f'worker-0{i}','observation':'executing','currentKeyword':'same','lastHeartbeatAt':'time','pendingVideoRetryTasks':123} for i in range(1,4)],
           'platformTasks':[{'platform':'小红书','source':'ok','counts':{'total':279,'completed':4,'pending':273,'leased':2,'validLeases':2,'failed':0}},
                            {'platform':'抖音','source':'ok','counts':{'total':279,'completed':11,'pending':268,'leased':0,'validLeases':0,'failed':0}}],
           'videos':{'checkpointStates':{'dead_letter':186},'reviewFlagCount':433},
           'productionOutputs':{'hourly':{'newVideos':17,'subtitleWrites':17}}}
        db={'source':'ok','posts':[{'project':'全国地产设计产品力监测','posts':5320,'subtitleNonempty':4389},
                                  {'project':'北京臻澐项目口碑','posts':121,'subtitleNonempty':0}],
            'otherPlatforms':[{'platform':'小红书','project':'a','posts':1185,'contentNonempty':204},
                              {'platform':'小红书','project':'b','posts':2476,'contentNonempty':557},
                              {'platform':'抖音','project':'a','posts':259,'contentNonempty':177}]}
        return s,db

    def test_representative_card_under_750_chars_and_30_lines(self):
        text,issues=brief_notification(*self.fixture())
        self.assertLess(len(text),750)
        self.assertLessEqual(len(text.splitlines()),34)
        for title in SECTION_TITLES:self.assertEqual(text.count(title),1)
        self.assertNotIn('最后心跳',text);self.assertNotIn('最近触达',text)
        self.assertNotIn('worker-01',text);self.assertNotIn('全国地产设计产品力监测',text)
        self.assertEqual(len(issues),0)

    def test_platform_aggregation_weighted_not_average_of_rates(self):
        text,_=brief_notification(*self.fixture())
        self.assertIn('视频号：入库 5,441 · 视频内容非空（全量） 80.7%',text)
        self.assertIn('小红书：入库 3,661 · 视频内容非空（全量） 20.8%',text)
        self.assertIn('完成✅ 4/276',text)
        self.assertNotIn('专题二视频内容非空0/121',text)

    def test_card_bold_headings_small_footnote_plain_dynamic_body(self):
        text,_=brief_notification(*self.fixture())
        elements=card(text,compact=True)['card']['elements']
        headings=[e['text']['content'] for e in elements if e.get('text',{}).get('tag')=='lark_md']
        self.assertEqual(headings,['**'+title+'**' for title in SECTION_TITLES])
        self.assertEqual(elements[-1]['tag'],'note')
        self.assertTrue(all('视频号' not in heading for heading in headings))

    def test_extra_diagnostics_retained_locally_and_bounded(self):
        s,db=self.fixture();s['recentErrors']=[{'worker':'worker-01'}]
        s['platformTasks'][0]['counts']['failed']=2
        text,issues=brief_notification(s,db,include_diagnostics=True)
        self.assertGreater(len(issues),3)
        self.assertIn(f'另{len(issues)-3}项待核查',text)

    def test_action_block_only_contains_retry_queue_tasks(self):
        s,db=self.fixture()
        s['keywordQueueCounts']={'states':{'retry_pending':2,'recollect_pending':3,'completed_with_deferred_retries':1,'running':4,'completed':10},'completedPendingImport':5}
        s['platformTasks'][0]['counts'].update(retryPending=7,pendingNew=200,failed=5,leased=2)
        s['platformTasks'][1]['counts'].update(retryPending=8,pendingNew=200,completed_with_skips=9)
        s['recentErrors']=[{'worker':'worker-01'}]
        db['otherPlatforms']=[{'platform':'小红书','posts':100,'titleNonempty':50,'coreMissing':50}]
        text,issues=brief_notification(s,db)
        action=text.split(SECTION_TITLES[3],1)[1].split('\n\n',1)[0]
        self.assertEqual(len(issues),3)
        self.assertIn('视频号：待重试 6 个关键词',action)
        self.assertIn('小红书：待重试 7 个关键词',action)
        self.assertIn('抖音：待重试 8 个关键词',action)
        for token in ('死信','待审核','核心字段','媒体类型','近期连接','机器异常'):
            self.assertNotIn(token,text)
        self.assertEqual(s['videos']['checkpointStates']['dead_letter'],186)

    def test_no_retry_tasks_does_not_treat_historical_quality_flags_as_failures(self):
        s,db=self.fixture()
        text,issues=brief_notification(s,db)
        self.assertEqual(issues,[])
        self.assertIn('未观察到失败后待重试的任务',text)

    def test_unavailable_source_does_not_invent_retry_task_counts(self):
        self.assertEqual(retry_task_issues({'sources':{'redis':'unavailable'},
            'keywordQueueCounts':{'retryPending':20},'platformTasks':[{'platform':'抖音',
                'source':'unavailable','counts':{'retryPending':30}}]}),[])

    def test_unavailable_sources_not_reported_as_zeros(self):
        text,_=brief_notification({'sources':{'redis':'unavailable'},'platformTasks':[{'platform':'抖音','source':'unavailable','counts':None}]},{'source':'unavailable'})
        self.assertIn('进度未知',text);self.assertIn('入库与非空率未知',text)
        self.assertNotIn('完成 0/0',text);self.assertNotIn('入库 0',text)

    def test_zero_failures_expired_leases_and_comments_not_repeated(self):
        text,_=brief_notification(*self.fixture())
        for token in ('失败0','过期租约0','已租出0','新增评论0'):self.assertNotIn(token,text)


if __name__=='__main__':unittest.main()
