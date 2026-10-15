import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from notification import brief_notification, SECTION_TITLES
from publish import card


class NotificationTests(unittest.TestCase):
    def test_video_no_change_completion_not_reported_as_success(self):
        snapshot,db=self.fixture();snapshot['videos']['noChangeCompleted']=7
        text,_=brief_notification(snapshot,db)
        self.assertIn('视频号补采：无变化结束 7（不计完整成功）',text)

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
        self.assertEqual(len(issues),2)

    def test_platform_aggregation_weighted_not_average_of_rates(self):
        text,_=brief_notification(*self.fixture())
        self.assertIn('视频号：入库 5,441 · 视频内容非空（全量） 80.7%',text)
        self.assertIn('小红书：入库 3,661 · 视频内容非空（全量） 20.8%',text)
        self.assertIn('确认完成 4/276',text)
        self.assertIn('专题二视频内容非空0/121',text)

    def test_card_bold_headings_small_footnote_plain_dynamic_body(self):
        text,_=brief_notification(*self.fixture())
        elements=card(text,compact=True)['card']['elements']
        headings=[e['text']['content'] for e in elements if e.get('text',{}).get('tag')=='lark_md']
        self.assertEqual(headings,['**'+title+'**' for title in SECTION_TITLES])
        self.assertEqual(elements[-1]['tag'],'note')
        self.assertTrue(all('视频号' not in heading for heading in headings))

    def test_extra_issues_retained_and_bounded(self):
        s,db=self.fixture();s['recentErrors']=[{'worker':'worker-01'}]
        s['platformTasks'][0]['counts']['failed']=2
        text,issues=brief_notification(s,db)
        self.assertGreater(len(issues),3)
        self.assertIn(f'另{len(issues)-3}项待核查',text)

    def test_unavailable_sources_not_reported_as_zeros(self):
        text,_=brief_notification({'sources':{'redis':'unavailable'},'platformTasks':[{'platform':'抖音','source':'unavailable','counts':None}]},{'source':'unavailable'})
        self.assertIn('进度未知',text);self.assertIn('入库与非空率未知',text)
        self.assertNotIn('完成 0/0',text);self.assertNotIn('入库 0',text)

    def test_zero_failures_expired_leases_and_comments_not_repeated(self):
        text,_=brief_notification(*self.fixture())
        for token in ('失败0','过期租约0','已租出0','新增评论0'):self.assertNotIn(token,text)


if __name__=='__main__':unittest.main()
