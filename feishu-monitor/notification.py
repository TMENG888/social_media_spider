"""Decision-first notification. Evidence and definitions stay in the full dashboard."""
from collections import Counter
from datetime import timezone, timedelta
from worker_visibility import reporting_snapshot, current_worker_rows
from worker_metrics import stamp
from task_activity import activity_text

SECTION_TITLES = ('① 关键词进度', '② 机器状态', '③ 数据质量与效率', '④ 异常与下一步')
FOOTER_PREFIX = '口径：'


def progress_line(platform, total, completed, retry, pending):
    """Presentation buckets only; never change the underlying queue states."""
    show = lambda value: str(value) if value is not None else '未确认'
    return f'{platform}：完成✅ {completed}/{total} · 重试 {show(retry)} · 待领 {show(pending)}'


def video_progress_line(snapshot, total):
    queue = snapshot.get('keywordQueueCounts') or {}
    states = queue.get('states')
    if states is None:
        # Old snapshots lack the raw state partition: do not invent a split.
        return progress_line('视频号', total['planned'], total['confirmed'], None, None)
    terminal = ('completed', 'completed_with_skips', 'completed_with_dead_letters', 'skipped_unresolved')
    new = ('pending', 'queued')
    ongoing = ('retry_pending', 'recollect_pending', 'completed_with_deferred_retries',
               'running', 'collecting', 'failed', 'import_pending', 'import_failed',
               'coverage_below_threshold', 'scan_completed_pending_verification', 'partial')
    closed = sum(states.get(state, 0) for state in terminal)
    pending_import = queue.get('completedPendingImport', 0)
    completed = max(0, closed - pending_import)
    pending = sum(states.get(state, 0) for state in new)
    retry = sum(states.get(state, 0) for state in ongoing) + pending_import
    if (set(states) - set(terminal + new + ongoing) or pending_import > closed
            or sum(states.values()) != total['planned']):
        retry = None
    return progress_line('视频号', total['planned'], completed, retry, pending)


def platform_progress_line(platform):
    counts = platform['counts']
    closed = sum(counts.get(state, 0) for state in ('completed', 'completed_with_skips', 'skipped_unresolved'))
    pending_import = platform.get('completedPendingImport', 0)
    completed = max(0, closed - pending_import)
    pending = counts.get('pendingNew')
    retry = counts.get('retryPending')
    if counts.get('pendingUnclassified'):
        pending = retry = None
    if retry is not None:
        retry += counts.get('leased', 0) + counts.get('failed', 0) + pending_import
    if counts.get('unknown') or pending_import > closed:
        retry = None
    return progress_line(platform['platform'], counts['total'], completed, retry, pending)


def retry_task_issues(snapshot):
    """Only explicit retry/recollection queues, not content flags or active leases."""
    issues = []
    if snapshot.get('sources', {}).get('redis') == 'ok':
        queue = snapshot.get('keywordQueueCounts') or {}
        states = queue.get('states')
        if states is not None:
            retry = sum(states.get(state, 0) for state in
                        ('retry_pending', 'recollect_pending', 'completed_with_deferred_retries'))
        else:
            retry = sum(queue.get(key, 0) for key in ('retryPending', 'recollectPending', 'deferred'))
        if retry:issues.append(f'视频号：待重试 {retry} 个关键词 → 按现有策略重试')
    for platform in snapshot.get('platformTasks', []):
        counts = platform.get('counts')
        if platform.get('source') == 'ok' and counts is not None and counts.get('retryPending'):
            issues.append(f"{platform['platform']}：待重试 {counts['retryPending']} 个关键词 → 按现有策略重试")
    return issues


def brief_notification(snapshot, db, *, include_diagnostics=False):
    snapshot = reporting_snapshot(snapshot)
    workers = current_worker_rows(snapshot.get('workers', []))
    platforms = snapshot.get('platformTasks', [])
    redis_ok = snapshot.get('sources', {}).get('redis') == 'ok'
    live_workers = [w for w in workers if w.get('observation') in ('executing', 'online_waiting')]
    # A computer can have multiple worker slots and historical stopped records.
    online_machines = {w['computer'] for w in live_workers if w.get('computer') not in (None, '', 'unknown')}
    unknown_machine_nodes = sum(w.get('computer') in (None, '', 'unknown') for w in live_workers)
    issues = []
    progress = [SECTION_TITLES[0]]
    if not redis_ok:
        progress.append('视频号：进度未知')
        issues.append('视频号Redis不可用 → 核对连接，勿将缺数当0')
    elif snapshot.get('progress'):
        total = Counter()
        for row in snapshot['progress'].values():
            total.update({key: row.get(key, 0) for key in ('planned', 'confirmed', 'mostly_completed', 'partial', 'uncollected', 'disposedWithSkips')})
        progress.append(video_progress_line(snapshot, total))
    else:
        progress.append('视频号：关键词进度暂不可确认')
    for p in platforms:
        counts = p.get('counts')
        if p.get('source') != 'ok' or counts is None:
            progress.append(p['platform'] + '：进度未知')
            issues.append(p['platform'] + '任务池暂不可确认 → 核对连接与批次')
            continue
        progress.append(platform_progress_line(p))
        for key, label in (('expiredLeases', '过期租约'), ('missingLeaseEvidence', '租约证据缺失'), ('unknown', '未知任务状态')):
            if counts.get(key):issues.append(f"{p['platform']}{label}{counts[key]} → 核对队列，不自动回收")
        if counts.get('failed'):issues.append(p['platform'] + '任务失败 → 查看失败原因并人工确认后续')
        # No lease is normal during rest/wait. Only independent stale heartbeat
        # or actual failed tasks may establish a machine/task anomaly.
        if p.get('unmatchedManifestTasks'):issues.append(p['platform'] + '专题清单未完全匹配 → 细分口径待核对')

    if workers:
        live_line = f'视频号：当前在线 {len(online_machines)}台' if online_machines else '视频号：当前无确认在线机器'
        live_line += f" · 执行 {sum(w.get('observation') == 'executing' for w in live_workers)}节点"
        executing = [w for w in live_workers if w.get('observation') == 'executing']
        if executing:live_line += '（' + activity_text(Counter(w.get('taskActivity', 'unknown') for w in executing)) + '）'
        waiting = sum(w.get('observation') == 'online_waiting' for w in live_workers)
        if waiting:live_line += f' · 等待 {waiting}节点'
        if unknown_machine_nodes:live_line += f' · 机器归属未知 {unknown_machine_nodes}节点'
        machines = [SECTION_TITLES[1], live_line]
    else:machines = [SECTION_TITLES[1], '视频号：机器状态未知']
    labels = {'heartbeat_stale': '心跳过期，运行待确认', 'registration_unobserved': '无注册心跳，运行待确认',
              'draining': '停止收尾中', 'exit_unconfirmed': '退出待确认', 'clock_skew': '时钟异常'}
    abnormal = [w for w in workers if w.get('observation') not in ('executing', 'online_waiting', 'stopped')]
    for w in abnormal[:2]:
        identity = f"{w['computer']}/{w['worker']}" if w.get('computer') else w['worker']
        machines.append(f"  {identity}：{labels.get(w.get('observation'), '待确认')}")
    if len(abnormal) > 2:machines.append(f'  另{len(abnormal)-2}个节点待核查，明细见看板')
    if abnormal:issues.append('视频号机器异常 → 核对心跳与收尾状态')
    for p in platforms:
        counts = p.get('counts')
        heartbeats=current_worker_rows(p.get('telemetry',{}).get('machines',[]))
        if heartbeats:
            active=sum(w['observation'] in ('executing','online_waiting','resting','cooldown') for w in heartbeats)
            resting=sum(w['observation'] in ('resting','cooldown') for w in heartbeats)
            machines.append(f"{p['platform']}：{active}/{len(heartbeats)} 在线（已上报）"+(f' · 休眠/冷却 {resting}' if resting else ''))
            stale=sum(w['observation'] in ('heartbeat_stale','clock_skew','unknown') for w in heartbeats)
            if stale:issues.append(f"{p['platform']}心跳异常{stale}台 → 核对节点；不据此重启")
        else:
            line=p['platform']+'：心跳未接入'
            if p.get('source') == 'ok' and counts is not None:line+=f" · 有效租约 {counts.get('validLeases',0)}"
            local=p.get('localProcesses',[])
            resting=sum(w['state']=='resting_or_waiting' for w in local)
            executing=sum(w['state']=='executing' for w in local)
            if resting:line+=f' · 本机休眠/等待 {resting}'
            elif executing:line+=f' · 本机运行 {executing}'
            machines.append(line)
        if p.get('telemetry',{}).get('source')=='unavailable':issues.append(p['platform']+'心跳遥测不可用 → 核对监控连接与权限')
        if counts is not None and p.get('source') == 'ok' and counts.get('validLeases'):
            activity = p.get('activeLeaseActivity')
            if activity is not None and sum(activity.values()) == counts['validLeases']:
                machines[-1] += ' · 租约：' + activity_text(activity)
            else:machines[-1] += ' · 当前任务类型未确认'

    quality = [SECTION_TITLES[2]]
    if db.get('source') != 'ok':
        quality.append('数据库不可用，入库与非空率未知')
        issues.append('数据库统计不可用 → 核对只读连接')
    else:
        grouped = {}
        def add(name,row):
            group=grouped.setdefault(name,Counter())
            for key in ('posts','titleNonempty','bodyNonempty','videoContentNonempty','videoEligible','videoEligibleNonempty','coreMissing','mediaTypeUnknown'):
                if key in row:group[key]+=int(row[key] or 0)
            if 'videoContentNonempty' not in row:group['legacyVideoContent']+=int(row.get('subtitleNonempty',row.get('contentNonempty',0)) or 0)
            if 'titleNonempty' not in row:group['legacyRows']+=int(row.get('posts') or 0)
        for row in db.get('posts', []):
            add('视频号',row)
            if int(row['posts'] or 0) > 0 and int(row['subtitleNonempty'] or 0) == 0:
                topic = '专题二' if row.get('project') == '北京臻澐项目口碑' else row.get('project', '项目')
                diagnostic=snapshot.get('videoDiagnostics',{}).get('topic2',{}) if topic=='专题二' else {}
                action='优先精准补采，不整体重置' if diagnostic.get('recoverableIdentityCount') else '核查字幕缺失原因'
                issues.append(f"视频号{topic}视频内容非空0/{row['posts']} → {action}")
        for row in db.get('otherPlatforms', []):
            add(row['platform'],row)
        for name, group in grouped.items():
            count=group['posts']
            def rate(n,d):return f'{n/d:.1%}' if d else '不适用'
            if group['legacyRows']:
                quality.append(f"{name}：入库 {count:,} · 视频内容非空（全量） {rate(group['legacyVideoContent'],count)} · 标题/正文待统计")
            else:
                body='不适用' if name in ('抖音','视频号') else rate(group['bodyNonempty'],count)
                quality.append(f"{name}：入库 {count:,} · 标题 {rate(group['titleNonempty'],count)} · 正文 {body} · 视频内容 {rate(group['videoEligibleNonempty'],group['videoEligible'])}")
                if group['coreMissing'] and name in ('小红书','抖音'):
                    issues.append(f"{name}核心字段待核验{group['coreMissing']}条 → 先复核缺失字段与媒体类型")
                if group['mediaTypeUnknown']:issues.append(f"{name}媒体类型未确认{group['mediaTypeUnknown']}条 → 补核适用范围")
        if not grouped:quality.append('配置项目暂无入库统计行')
    hourly = snapshot.get('productionOutputs', {}).get('hourly')
    if hourly:
        quality.append(f"视频号近1h：新增 {hourly['newVideos']} · 视频内容写入 {hourly['subtitleWrites']}")
    else:quality.append('视频号近1h产出：暂无可验证事件')
    for p in platforms:
        output=p.get('telemetry',{}).get('hourly')
        if output:
            quality.append(f"{p['platform']}近1h：新增 {output['newPosts']} · 视频内容写入 {output['videoContentWrites']}（已上报节点）")
            continue
        growth=db.get('collectionEfficiency',{}).get(p['platform'],{})
        if growth.get('source')=='sampled_net_growth':
            minutes=round(growth['windowSeconds']/60)
            quality.append(f"{p['platform']}观测{minutes}m：入库净增 {growth['netPosts']:+d} · 视频内容净增 {growth['netVideoContent']:+d}")
            if growth.get('negativeDelta'):issues.append(p['platform']+'累计计数下降 → 核对统计范围与数据变化')
        else:quality.append(p['platform']+'效率：累积观测中，非确认零产出')
    checkpoint = snapshot.get('videos', {}).get('checkpointStates', {})
    dead = checkpoint.get('dead_letter', 0); review = snapshot.get('videos', {}).get('reviewFlagCount', 0)
    if redis_ok and (dead or review):
        issues.append(f'视频号死信{dead} / 待审核{review} → 优先复核，断点可能重复')
    if snapshot.get('recentErrors'):issues.append('近期连接/入库异常 → 看板定位原因')
    # Historical content/quality flags remain local; the group action block is
    # restricted to task retry states. Never mutate tasks to silence a warning.
    def priority(issue):
        if any(word in issue for word in ('不可用','暂不可确认','心跳异常')):return 0
        if any(word in issue for word in ('任务失败','过期租约','死信','证据缺失')):return 1
        if '非空0/' in issue:return 2
        return 3
    retry_issues = retry_task_issues(snapshot)
    all_issues = sorted(dict.fromkeys(issues + retry_issues if include_diagnostics else retry_issues),key=priority)
    actions = [SECTION_TITLES[3]] + (all_issues[:3] or ['未观察到失败后待重试的任务'])
    if len(all_issues) > 3:actions.append(f'另{len(all_issues)-3}项待核查，见本机看板')
    generated = stamp(snapshot.get('generatedAt'))
    when = generated.astimezone(timezone(timedelta(hours=8))).strftime('%m-%d %H:%M') if generated else '时间未确认'
    headline = f"{when}（北京）｜{str(len(all_issues))+'项需关注' if all_issues else '未观察到失败待重试任务'}"
    notes = ['完成含跳过结案，非全量采齐；重试含执行中、补采/重采及待入库；待领为未尝试', '入库历史累计；字段非空≠合格；视频内容仅视频行；净增≠新增']
    if platforms:
        notes += ['有效租约不等于确认在线', '百度资讯/公众号未接入']
    if any(w.get('observation') in ('heartbeat_stale', 'registration_unobserved') for w in workers):
        notes.append('无心跳不代表已安全退出或保存断点')
    notes.append('打标质量/耗时/成本未知；明细见本机看板')
    footer = FOOTER_PREFIX + '；'.join(notes) + '。'
    return '\n\n'.join([headline, '\n'.join(progress), '\n'.join(machines), '\n'.join(quality), '\n'.join(actions), footer]), all_issues
