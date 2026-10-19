"""Build previews by default. --send explicitly opts into a Feishu webhook POST."""
import argparse, base64, hashlib, hmac, html, json, os, sys, time, urllib.request
from pathlib import Path
from urllib.parse import urlparse
from datetime import timezone,timedelta
sys.path.insert(0,str(Path(__file__).resolve().parent))
from collect import ROOT, atomic_json, parse_time
from worker_visibility import reporting_snapshot, current_worker_rows
from report_archive import archive_confirmed, render_recent_day
from notification import brief_notification, SECTION_TITLES, FOOTER_PREFIX
from collection_efficiency import observe_efficiency

def display_time(value):
    dt=parse_time(value)
    return dt.astimezone(timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M:%S（北京时间）') if dt else '暂无记录'

def elapsed(value):
    if value is None:return '未知'
    if value<0:return '时钟超前，需核对'
    if value<60:return f'{value:.0f}秒'
    if value<3600:return f'{value/60:.1f}分钟'
    return f'{value/3600:.1f}小时'

WORKER_LABELS={'stopped':'已安全停止','executing':'在线执行','online_waiting':'在线等待任务','draining':'安全停止收尾中','heartbeat_stale':'已停止（心跳中断，监控判定；退出及断点保存未确认）','clock_skew':'时钟异常','exit_unconfirmed':'退出但收尾未确认','registration_unobserved':'已停止（监控口径：无在线心跳；正常退出未确认）','verified_output_only':'仅观察到有效产出'}

def summary(snapshot,db):
    snapshot=reporting_snapshot(snapshot)
    lines=[f"跨平台采集监控｜{snapshot.get('generatedAt','未知时间')}",f"视频号任务批次：{snapshot.get('runId','未知')}","","【进度：Redis状态确认，不等同数据库完整性审计】"]
    for platform in snapshot.get('platformTasks',[]):
        lines.append(f"{platform['platform']}：数据源{platform.get('source','未知')}；批次{platform.get('campaign','未确认')}；采样{display_time(platform.get('generatedAt'))}")
        if platform.get('counts') is not None:
            lines.append('  状态计数：'+json.dumps(platform['counts'],ensure_ascii=False))
            lines.append('  专题：'+json.dumps(platform.get('topics',{}),ensure_ascii=False))
            lines.append('  租约归属：'+json.dumps(platform.get('workers',[]),ensure_ascii=False))
            lines.append('  完成结果状态：'+json.dumps(platform.get('completedResultStates',{}),ensure_ascii=False))
        lines.append('  '+platform.get('scope','当前生产队列不可确认；不是零任务。'))
        lines.append('  Redis队列完成不等于数据质量合格；租约不是机器心跳。')
        lines.append('  独立心跳与产出遥测：'+json.dumps(platform.get('telemetry',{}),ensure_ascii=False))
        lines.append('  本机实时进程观察（非跨机器心跳）：'+json.dumps(platform.get('localProcesses',[]),ensure_ascii=False))
    if snapshot.get('sources',{}).get('redis')!='ok':lines.append('Redis不可用，进度未知；不是零任务。')
    for topic,p in snapshot.get('progress',{}).items():
        lines.append(f"{topic}：计划{p['planned']}，确认完成{p['confirmed']}，基本完成{p.get('mostly_completed',0)}，采集中/待补采{p['partial']}，未采集到有效视频数据{p.get('uncollected',p.get('waiting',0))}")
    threshold=snapshot.get('progressDefinition',{}).get('mostlyCompletedThreshold',0.8)
    lines.append(f"基本完成：列表遍历已结束、断点检查通过，且已知视频完成比例≥{threshold:.0%}；剩余异常仍需补采。")
    lines.append('未采集到有效视频数据：本批次Redis无视频断点，包含未尝试或搜索失败；不代表数据库没有历史数据。')
    lines+=['','【机器状态｜注册心跳与任务租约分开】']
    for w in snapshot.get('workers',[]):
        state=w.get('observation');label=WORKER_LABELS.get(state,'状态证据不足')
        lines.append(f"{w['worker']} / {w.get('computer') or '主机未确认'}：{label}")
        keyword=w.get('currentKeyword') or ('无（已停止）' if state=='stopped' else '无（等待领取）' if state=='online_waiting' else '未确认')
        lines.append(f"  当前关键词：{keyword}；任务状态：{w.get('taskStatus') or '未观察到'}")
        if state=='executing':lines.append('  当前执行：'+{'new':'新任务','retry':'重试任务'}.get(w.get('taskActivity'),'类型未确认')+'；依据：'+w.get('taskActivityEvidence','未观察到'))
        if w.get('taskKind') or w.get('taskStartedAt'):lines.append(f"  类型：{w.get('taskKind') or '未知'}；开始：{display_time(w.get('taskStartedAt'))}")
        lines.append(f"  最后注册心跳：{display_time(w.get('lastHeartbeatAt'))}；距采样 {elapsed(w.get('heartbeatAgeSeconds'))}")
        lines.append(f"  最近日志：{display_time(w.get('lastLogAt'))}；最近观察关键词：{w.get('lastObservedKeyword') or '暂无'}（不代表当前任务）")
        if w.get('stopAckStatus'):lines.append(f"  停止回执：{w['stopAckStatus']}，{display_time(w.get('stopAckAt'))}")
        leases=w.get('leases',[])
        if leases:
            lines.append(f"  名下pending消息：{w.get('pendingLeaseCount','未知')}；最近触达详情（最多3条）：")
            for lease in leases:
                status='达到回收阈值' if lease.get('reclaimEligible') else '尚未达到回收阈值'
                threshold_note='（监控默认值）' if lease.get('reclaimThresholdSource')=='monitor_default' else ''
                lines.append(f"    {lease['stream']}｜{lease.get('keyword') or lease.get('taskId') or '任务身份未读取'}｜消息{lease['messageId']}；触达{display_time(lease.get('lastTouchAt'))}；空闲{elapsed(lease.get('leaseIdleMs',0)/1000)}；阈值{lease.get('reclaimAfterSeconds',300)}秒{threshold_note}，{status}")
            if state=='stopped':lines.append('  此为停止后的遗留待回收消息，不代表机器仍在采集。')
            if not w.get('registrationObserved'):lines.append('  以上为最近日志consumer名下的遗留消息；不能据此认定机器仍在执行。')
        else:lines.append('  当前没有观察到名下pending租约；等待领取时没有任务租约是正常情况。' if w.get('registrationObserved') else '  没有可归属的租约证据，不能用历史日志推断当前执行情况。')
        if w.get('lastEffectiveOutputAt'):output=display_time(w['lastEffectiveOutputAt'])
        elif w.get('registrationObserved'):output='暂无提交并读回验证的新产出；不据此判断代码未更新。重复跳过/无变化不计产出。'
        else:output='未观察到可归属的已验证产出事件；不能等同没有历史入库。'
        lines.append('  最近有效产出：'+output)
        if w.get('effectiveOutputEvidence'):
            lines.append(f"  元数据：{display_time(w.get('lastMetadataAt'))}；字幕：{display_time(w.get('lastSubtitleAt'))}；评论：{display_time(w.get('lastCommentAt'))}（实际提交并读回验证）")
    lines+=['','【数据质量：配置专题在数据库的累计数据，非仅当前批次】']
    if db.get('source')!='ok':lines.append('数据库不可用：入库条数与非空率未知。')
    for row in db.get('posts',[]):
        rate=100*int(row['subtitleNonempty'] or 0)/int(row['posts']) if row['posts'] else 0
        lines.append(f"{row['project']}：入库{row['posts']}，字幕非空{row['subtitleNonempty']}（{rate:.1f}%）；非空不代表合格")
    for row in db.get('comments',[]):lines.append(f"{row['project']}：评论表{row['comments']}条（无法据此认定每条视频评论已采齐）")
    for row in db.get('otherPlatforms',[]):
        count=int(row['posts'] or 0);nonempty=int(row['contentNonempty'] or 0)
        rate=f'{nonempty/count:.1%}' if count else '无数据'
        lines.append(f"{row['platform']} / {row['project']}：历史入库{count}，内容非空{rate}；非空不代表质量合格。")
    lines.append('核心字段原始计数与适用分母：'+json.dumps(db.get('posts',[])+db.get('otherPlatforms',[]),ensure_ascii=False))
    lines.append('视频号专题诊断（断点可能跨关键词重复）：'+json.dumps(snapshot.get('videoDiagnostics',{}),ensure_ascii=False))
    lines.append(f"Redis明确待审核标记：{snapshot.get('videos',{}).get('reviewFlagCount','未知')}；没有标记不代表没有污染")
    lines+=['','【效率】']
    lines.append('跨快照全平台数据库净增观测（非gross新增/提交事件）：'+json.dumps(db.get('collectionEfficiency',{}),ensure_ascii=False))
    hourly=snapshot.get('productionOutputs',{}).get('hourly')
    if hourly:
        lines.append(f"最近1小时已验证产出：新增视频{hourly['newVideos']}，元数据有效更新{hourly['metadataUpdates']}，字幕写入{hourly['subtitleWrites']}，新增评论{hourly['newComments']}，评论有效更新{hourly['commentUpdates']}。仅覆盖部署新代码后的事件。")
    else:lines.append('每小时实际入库量：暂无已验证产出记录；不是确认无产出。')
    for w in snapshot.get('productionOutputs',{}).get('perWorker',[]):
        lines.append(f"  {w.get('worker')} / {w.get('computer')}：新增视频{w['newVideos']}，字幕写入{w['subtitleWrites']}，新增评论{w['newComments']}（最近1小时，已验证事务）")
    phase=snapshot.get('phaseEfficiency',{})
    lines.append(f"近1小时日志样本：ASR完成{phase.get('asrSamples',0)}条、生产门槛接受{phase.get('asrProductionAccepted',0)}条；平均转写{str(phase['averageAsrSeconds'])+'秒' if phase.get('averageAsrSeconds') is not None else '暂无样本'}。有界日志未观察到不等于实际没有工作；转写完成不等于数据库更新成功。")
    if phase.get('recordingSamples'):lines.append(f"录音样本{phase['recordingSamples']}条，平均录音{phase['averageRecordingSeconds']}秒；不是单视频完整采集耗时。")
    if phase.get('taskSamples'):lines.append(f"子任务收尾样本{phase['taskSamples']}次，平均耗时{phase['averageTaskSeconds']}秒（包含失败/无变化，不能当单视频成功耗时）。")
    rate=snapshot.get('progressEfficiency',{})
    if rate.get('netCompletedPerHour') is not None:lines.append(f"观察{elapsed(rate.get('windowSeconds'))}，视频断点净完成+{rate.get('netCompleted')}，约{rate['netCompletedPerHour']}条/小时（与入库量分开）。")
    else:lines.append('断点净完成速率：正在积累跨快照样本，不能用累计完成数代替实时速率。')
    eta=rate.get('knownBacklogEtaHours')
    if eta:lines.append(f"当前已知未完成视频断点{rate.get('knownRemaining')}条，按最近净完成速率情景预估{eta[0]}～{eta[1]}小时；跨关键词可能重复，不含新关键词发现的视频，非统计置信区间。")
    else:
        reasons={'no_confirmed_active_worker':'当前没有确认活跃的注册机器','observation_window_too_short':'连续观察不足15分钟','insufficient_net_completions':'净完成样本少于5条或净速率为0','checkpoint_count_decreased':'断点完成数下降，不能按当前样本外推'}
        lines.append('剩余时间：暂不预估（'+reasons.get(rate.get('etaUnavailableReason'),'证据不足')+'）。未遍历关键词的最终视频量未知，不能声称这是全量完成时间。')
    lines+=['字幕非空/生产质量门槛接受均不等同人工准确率；单视频端到端耗时未标准化。','','【异常与积压】']
    counts=snapshot.get('videos',{}).get('checkpointStates',{})
    lines.append(f"视频断点：{json.dumps(counts,ensure_ascii=False)}")
    for name,stream in snapshot.get('streams',{}).items():
        for group in stream.get('groups',[]):lines.append(f"{name}：pending消息{group.get('pending')}，未读lag {group.get('lag') if group.get('lag') is not None else '未知'}（消息数不是唯一视频数）")
        if stream.get('pendingSampleTruncated'):lines.append(f'{name}：租约扫描达到上限，机器名下pending数仅为抽样下限。')
    lines.append(f"最近一小时连接/入库异常证据{len(snapshot.get('recentErrors',[]))}条（有界日志抽样）")
    lines+=['','注：注册每约3秒更新；心跳超时不直接证明进程死亡。历史日志/租约非存活证据；扫描与日志样本有界。']
    return '\n'.join(lines)

def push_summary(snapshot,db):
    return brief_notification(snapshot,db)[0]


def stamp_time_short(value):
    dt=parse_time(value)
    return dt.astimezone(timezone(timedelta(hours=8))).strftime('%m-%d %H:%M') if dt else '未观察到'

def card(text,url='',compact=False):
    elements=[]
    for block in text[:12000].split('\n\n'):
        if compact and block.startswith(FOOTER_PREFIX):
            elements.append({'tag':'note','elements':[{'tag':'plain_text','content':block}]})
            continue
        if elements:elements.append({'tag':'hr'})
        lines=block.split('\n')
        if compact and lines[0] in SECTION_TITLES:
            elements.append({'tag':'div','text':{'tag':'lark_md','content':'**'+lines[0]+'**'}})
            elements.append({'tag':'div','text':{'tag':'plain_text','content':'\n'.join(lines[1:])}})
        else:elements.append({'tag':'div','text':{'tag':'plain_text','content':block}})
    if url.startswith('https://'):elements.append({'tag':'action','actions':[{'tag':'button','text':{'tag':'plain_text','content':'打开监控看板'},'url':url,'type':'primary'}]})
    template='orange' if compact and '项需关注' in text.split('\n',1)[0] else 'blue'
    return {'msg_type':'interactive','card':{'config':{'wide_screen_mode':True},'header':{'template':template,'title':{'tag':'plain_text','content':'跨平台采集摘要'}},'elements':elements}}

def alert_signature(snapshot,db):
    snapshot=reporting_snapshot(snapshot)
    # Counts/timestamps do not cause repeat alerts. Event expiry is NOT a proof of recovery.
    platform_states=[]
    for platform in snapshot.get('platformTasks',[]):
        counts=platform.get('counts') or {}
        worker_states=sorted((w['worker'],bool(w.get('validLeases')),bool(w.get('expiredLeases'))) for w in platform.get('workers',[]))
        platform_states.append((platform['platform'],platform.get('source'),bool(counts.get('failed')),bool(counts.get('expiredLeases')),worker_states))
    states={'redis':snapshot.get('sources',{}).get('redis'),'database':db.get('source'),
            'workers':sorted((w.get('computer') or '',w.get('worker') or '',w.get('observation') or '') for w in current_worker_rows(snapshot.get('workers',[]))),
            'platforms':sorted(platform_states)}
    return hashlib.sha256(json.dumps(states,sort_keys=True).encode()).hexdigest()

def progress_signature(snapshot):
    snapshot=reporting_snapshot(snapshot)
    values={'generation':snapshot.get('generation'),'counts':snapshot.get('videos',{}).get('checkpointStates',{}),
            'outputs':sorted((r.get('computer') or '',r.get('worker') or '',r.get('lastEffectiveOutputAt') or '') for r in snapshot.get('productionOutputs',{}).get('latest',[])),
            'platforms':[(p['platform'],p.get('campaign'),p.get('counts'),p.get('topics')) for p in sorted(snapshot.get('platformTasks',[]),key=lambda p:p['platform'])]}
    return hashlib.sha256(json.dumps(values,sort_keys=True).encode()).hexdigest()

def should_send(previous,snapshot,db,now_seconds,alerts_only=False,watch=False):
    if not alerts_only and not watch:return True
    if previous.get('sourceSignature')!=alert_signature(snapshot,db):return True
    return watch and now_seconds-previous.get('deliveredAt',0)>=900 and previous.get('progressSignature')!=progress_signature(snapshot)

def send(payload,webhook,secret=''):
    u=urlparse(webhook)
    if u.scheme!='https' or u.hostname!='open.feishu.cn' or not u.path.startswith('/open-apis/bot/v2/hook/') or u.username or u.password:
        raise ValueError('Expected official HTTPS Feishu custom-bot webhook')
    if secret:
        stamp=str(int(time.time()));payload={**payload,'timestamp':stamp,'sign':base64.b64encode(hmac.new((stamp+'\n'+secret).encode(),b'',hashlib.sha256).digest()).decode()}
    req=urllib.request.Request(webhook,json.dumps(payload,ensure_ascii=False).encode(),{'Content-Type':'application/json'},method='POST')
    with urllib.request.urlopen(req,timeout=15) as response:result=json.load(response)
    code=result.get('code',result.get('StatusCode'))
    if code!=0:
        safe_code=str(code) if isinstance(code,(int,float)) else 'unknown'
        raise RuntimeError('Feishu rejected payload; status code '+safe_code+'; delivery not confirmed')
    return True

def build(snapshot,db,config,out):
    snapshot=reporting_snapshot(snapshot)
    short,issues=brief_notification(snapshot,db)
    diagnostics=brief_notification(snapshot,db,include_diagnostics=True)[1]
    text=summary(snapshot,db)+'\n\n【本机诊断清单（飞书仅展示待重试任务）】\n'+('\n'.join(diagnostics) if diagnostics else '未观察到需新增处理的异常。')
    payload=card(short,config.get('dashboard_url',''),compact=True)
    out.mkdir(parents=True,exist_ok=True)
    render_recent_day(out,int(time.time()))
    atomic_json(out/'snapshot.json',{'redis':snapshot,'database':db})
    atomic_json(out/'feishu-card.json',payload)
    atomic_json(out/'push-preview.json',{'generatedAt':snapshot.get('generatedAt'),'text':short})
    # Local preview only: no credentials, raw logs or subtitle contents included.
    labels={'confirmed':'确认完成','mostly_completed':'基本完成（少量待补采）','partial':'采集中／仍需较多补采','uncollected':'未采集到有效视频数据'}
    tables=[]
    for category,label in labels.items():
        rows=[r for r in snapshot.get('keywords',[]) if r['category']==category]
        cells=[]
        for r in rows:
            ratio=f"{r['completionRatio']:.1%}" if r.get('completionRatio') is not None else '未知'
            vals=[r['topic'],r['keyword'],str(r['completedVideos'])+'/'+str(r['knownVideos']),ratio,str(r['unresolvedVideos']),r['redisStatus'],'有过尝试' if r['attempted'] else '未尝试']
            cells.append('<tr>'+''.join('<td>'+html.escape(v)+'</td>' for v in vals)+'</tr>')
        tables.append('<details><summary>'+label+'：'+str(len(rows))+' 个关键词（点击展开）</summary><table><thead><tr><th>专题</th><th>关键词</th><th>已完成/已知视频</th><th>完成率</th><th>未解决</th><th>Redis状态</th><th>执行记录</th></tr></thead><tbody>'+''.join(cells)+'</tbody></table></details>')
    content='<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>跨平台采集监控</title><style>body{background:#f5f7fb;color:#24324b;font:16px/1.8 system-ui;margin:40px auto;max-width:1200px}h1{color:#245bda}article{white-space:pre-wrap;background:white;border-radius:16px;padding:32px;box-shadow:0 4px 30px #18386910}footer{color:#697891}details{background:white;margin:16px 0;padding:20px;border-radius:12px;overflow:auto}summary{cursor:pointer;font-weight:600}table{border-collapse:collapse;width:100%;font-size:14px}td,th{text-align:left;padding:8px;border-bottom:1px solid #e2e8f0}</style><h1>跨平台采集监控 · 试运行</h1><article>'+html.escape(short)+'</article><h2>只读证据详情</h2><article>'+html.escape(text)+'</article><h2>视频号关键词分组明细</h2>'+''.join(tables)+'<footer>本机只读预览；发送确认与云文档同步须分别核对。</footer></html>'
    tmp=out/'dashboard.html.tmp';tmp.write_text(content,encoding='utf-8');os.replace(tmp,out/'dashboard.html')
    return payload

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--send',action='store_true');p.add_argument('--alerts-only',action='store_true');p.add_argument('--watch',action='store_true');a=p.parse_args()
    out=ROOT/'output';config=json.loads((ROOT/'config.json').read_text(encoding='utf-8'))
    snapshot=json.loads((out/'redis.json').read_text(encoding='utf-8'));db=json.loads((out/'database.json').read_text(encoding='utf-8'))
    snapshot['platformTasks']=[]
    for platform in ('小红书','抖音'):
        try:
            observation=json.loads((out/('platform-'+platform+'.json')).read_text(encoding='utf-8'))
            observed=parse_time(observation.get('generatedAt'))
            sampled=parse_time(snapshot.get('generatedAt'))
            if observed is None or sampled is None or abs((observed-sampled).total_seconds())>300:
                raise ValueError('Stale platform observation')
        except (OSError,ValueError):observation={'platform':platform,'source':'unavailable','counts':None}
        snapshot['platformTasks'].append(observation)
    db['collectionEfficiency']=observe_efficiency(out,db)
    payload=build(snapshot,db,config,out)
    sig=alert_signature(snapshot,db);statefile=out/'delivery-state.json'
    previous=json.loads(statefile.read_text(encoding='utf-8')) if statefile.exists() else {}
    if a.send and should_send(previous,snapshot,db,int(time.time()),a.alerts_only,a.watch):
        webhook=os.environ.get('FEISHU_WEBHOOK','');secret=os.environ.get('FEISHU_SIGN_SECRET','')
        if not webhook:raise SystemExit('Webhook absent; no message sent')
        try:send(payload,webhook,secret)
        except Exception as e:
            detail=str(e) if isinstance(e,RuntimeError) and str(e).startswith('Feishu rejected payload; status code ') else type(e).__name__
            raise SystemExit('Push failed: '+detail+' (credential-bearing URL omitted)')
        delivered_at=int(time.time())
        atomic_json(statefile,{'sourceSignature':sig,'progressSignature':progress_signature(snapshot),'deliveredAt':delivered_at});print('Feishu delivery confirmed',flush=True)
        try:
            archive_confirmed(out,snapshot,db,payload,push_summary(snapshot,db),delivered_at)
        except Exception as e:
            raise SystemExit('Delivery confirmed, but local report archive failed: '+type(e).__name__)
        print('Confirmed report archived locally; cloud document sync requires separate verification')
    else:print('Preview generated; no message sent')
