"""Read-only Redis observability. Never ACK/claim/reset tasks or modify Redis."""
import argparse, collections, hashlib, json, os, sys, tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT.parent/'common/src'))
from redis_task_queue import RedisConnection, flatten_queue, retry_payload_has_identity
from production_metrics import read_outputs
from worker_metrics import stamp, worker_states, phase_metrics, progress_rate
from worker_visibility import reportable_worker

def atomic_json(path,data):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(prefix=path.name+'.tmp-',dir=path.parent)
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as f:
            json.dump(data,f,ensure_ascii=False,indent=2);f.flush();os.fsync(f.fileno())
        os.replace(tmp,path)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)

def pairs(values):return dict(zip(values[::2],values[1::2]))
def hscan(c,key):
    cursor='0'
    while True:
        cursor,values=c.command('HSCAN',key,cursor,'COUNT',300)
        yield from pairs(values).items()
        if str(cursor)=='0':break
def scan(c,pattern):
    cursor='0';seen=set()
    while True:
        cursor,keys=c.command('SCAN',cursor,'MATCH',pattern,'COUNT',100)
        for key in keys:
            if key not in seen:seen.add(key);yield key
        if str(cursor)=='0':break
def json_value(raw):
    try:return json.loads(raw)
    except (ValueError,TypeError):return {}
def parse_time(value):
    return stamp(value)

def progress(tasks,statuses,video_counts,mostly_completed_ratio=0.8):
    if not 0 < mostly_completed_ratio < 1:
        raise ValueError('mostly_completed_ratio must be between 0 and 1')
    topics={};details=[]
    for task in tasks:
        record=statuses.get(task['task_id'],{});state=record.get('status','unseen')
        counts=video_counts.get(task['task_id'],{})
        # Deferred work and dead letters always prevent final completion.
        blockers=sum(n for s,n in counts.items() if s!='completed')
        total=sum(counts.values());completed=counts.get('completed',0)
        ratio=completed/total if total else None
        traversal_finished=record.get('scanCompleted') is not False and state in ('completed','completed_with_deferred_retries','completed_with_skips','completed_with_dead_letters')
        guard_ok=record.get('checkpointGuard',{}).get('ok') is True
        if state=='completed' and blockers==0 and guard_ok:
            category='confirmed'
        elif total and traversal_finished and guard_ok and ratio>=mostly_completed_ratio:
            category='mostly_completed'
        elif not total and state not in ('running','collecting'):
            category='uncollected'
        else:
            category='partial'
        topic=topics.setdefault(task['topic'],dict(planned=0,confirmed=0,mostly_completed=0,partial=0,uncollected=0))
        topic['planned']+=1;topic[category]+=1
        disposed=traversal_finished and state in ('completed_with_skips','completed_with_dead_letters') and not any(
            n for s,n in counts.items() if s not in ('completed','no_content','not_applicable','dead_letter','skipped_unresolved'))
        topic['disposedWithSkips']=topic.get('disposedWithSkips',0)+int(disposed)
        details.append(dict(topic=task['topic'],keyword=task['keyword'],taskId=task['task_id'],category=category,redisStatus=state,videoStates=dict(counts),completedVideos=completed,knownVideos=total,unresolvedVideos=blockers,completionRatio=ratio,traversalFinished=traversal_finished,attempted=state!='unseen'))
    return topics,details

def collect(config):
    now=datetime.now(timezone.utc);prefix='wechat:channels:'+config['run_id']
    tasks=flatten_queue(json.loads((ROOT/config['queue']).read_text(encoding='utf-8-sig')))
    result={'generatedAt':now.astimezone(timezone(timedelta(hours=8))).isoformat(),'runId':config['run_id'],'sources':{},'warnings':[]}
    secret=(ROOT/config['redis_credential']).read_text(encoding='utf-8-sig').strip()
    with RedisConnection(config['redis_url'],secret,timeout=8) as c:
        result['sources']['redis']='ok';result['generation']=c.command('GET',prefix+':generation')
        statuses={key:json_value(raw) for key,raw in hscan(c,prefix+':status')}
        counts={};total=collections.Counter();reviews=0;no_change=0;latest_output={};asr_status=collections.Counter()
        task_topics={task['task_id']:task['topic'] for task in tasks}
        diagnostics={}
        for key in scan(c,prefix+':video-state:*'):
            task_id=key.split(':video-state:',1)[1].replace('_',':',1)
            per=collections.Counter()
            # HSCAN may return a field more than once during concurrent changes.
            for fp,raw in dict(hscan(c,key)).items():
                cp=json_value(raw);state=cp.get('status','unknown');per[state]+=1;total[state]+=1
                if state=='skipped_unresolved' and cp.get('disposition')=='no_change':no_change+=1
                asr_status[cp.get('asr_status','unknown')]+=1
                topic=task_topics.get(task_id,'未匹配专题')
                diag=diagnostics.setdefault(topic,{'checkpointStates':collections.Counter(),'asrStates':collections.Counter(),'rowVideoContentNonempty':0,'checkpoints':0,'savedLinkCount':0,'recoverableIdentityCount':0,'lastErrors':collections.Counter()})
                diag['checkpointStates'][state]+=1;diag['asrStates'][cp.get('asr_status','unknown')]+=1;diag['checkpoints']+=1
                if str((cp.get('row') or {}).get('video_content') or '').strip():diag['rowVideoContentNonempty']+=1
                if (cp.get('row') or {}).get('url'):diag['savedLinkCount']+=1
                if retry_payload_has_identity(cp):diag['recoverableIdentityCount']+=1
                error=str(cp.get('last_error') or '')
                # Stable categories only, never raw errors or document content.
                if error:
                    kind=next((name for name,terms in (
                        ('subtitle_reconciliation',('Subtitle reconciliation:',)),
                        ('identity_recovery',('identity_recovery_required',)),
                        ('retry_audit',('Retry audit','retry audit','retry_pending')),
                        ('audio_unavailable',('audio','Audio','录音','silence','speech')),
                        ('quality_review',('review','implausibly','quality','quality-gated')),
                        ('search_unavailable',('search','Search','搜索')),
                        ('timeout',('timeout','Timeout','超时')),
                        ('database',('MySQL','mysql','数据库'))
                    ) if any(term in error for term in terms)),'other')
                    diag['lastErrors'][kind]+=1
                if state not in ('skipped_unresolved','dead_letter') and (cp.get('subtitle_review_required') or cp.get('asr_status') in ('review','partial_review')):reviews+=1
                stamp=cp.get('updated_at');dt=parse_time(stamp)
                if state=='completed' and dt and (task_id not in latest_output or dt>parse_time(latest_output[task_id])):latest_output[task_id]=stamp
            counts[task_id]=per
        result['progress'],result['keywords']=progress(tasks,statuses,counts,float(config.get('mostly_completed_ratio',0.8)))
        keyword_states=collections.Counter(statuses.get(task['task_id'],{}).get('status','unseen') for task in tasks)
        result['keywordQueueCounts']={'pendingNew':sum(keyword_states[s] for s in ('pending','queued')),
            'retryPending':keyword_states['retry_pending'],'deferred':keyword_states['completed_with_deferred_retries'],
            'unobserved':keyword_states['unseen'],'states':dict(keyword_states),
            'definition':'待领=pending/queued关键词；重试=retry_pending关键词；补采=遍历结束但视频补采未完成的关键词；unseen未知不默认待领。不是视频重试消息数。'}
        result['progressDefinition']={'mostlyCompletedThreshold':config.get('mostly_completed_ratio',0.8),'denominator':'known video checkpoints for each keyword, not platform total','uncollected':'no checkpoints in this Redis run; may have previous MySQL data or failed search attempts'}
        result['videos']={'checkpointStates':dict(total),'noChangeCompleted':no_change,'asrStates':dict(asr_status),'reviewFlagCount':reviews,'reviewScope':'explicit Redis flags only; not a full subtitle quality audit'}
        result['videoDiagnostics']=diagnostics
        registry={key:json_value(raw) for key,raw in hscan(c,prefix+':worker-registry')}
        registry={key:r for key,r in registry.items() if reportable_worker(r.get('worker'))}
        acks={key:json_value(raw) for key,raw in hscan(c,prefix+':worker-control-acks')}
        streams={};pending_by_worker={};stream_names={'tasks':prefix+':tasks','video-retry':prefix+':video-retry'}
        round_info=pairs(c.command('HGETALL',prefix+':retry-round') or [])
        if round_info.get('stream','').startswith(prefix+':retry-round:'):
            stream_names['retry-round']=round_info['stream']
        result['retryRound']={k:round_info.get(k) for k in ('state','id','planned','startedAt','finishedAt')}
        for name,key in stream_names.items():
            if c.command('TYPE',key)!='stream':streams[name]={'available':False};continue
            groups=[pairs(g) for g in c.command('XINFO','GROUPS',key)]
            streams[name]={'length':c.command('XLEN',key),'groups':groups,'note':'message count is not unique video count'}
            for group in groups:
                cursor='-';observed=0;limit=config.get('pending_limit',10000)
                while observed<limit:
                    page=c.command('XPENDING',key,group['name'],cursor,'+',min(500,limit-observed)) or []
                    if not page:break
                    for mid,consumer,idle,deliveries in page:
                        pending_by_worker.setdefault(consumer,[]).append({'stream':name,'streamKey':key,'group':group['name'],'messageId':mid,'leaseIdleMs':idle,'deliveries':deliveries})
                    observed+=len(page);cursor='('+page[-1][0]
                    if len(page)<500:break
                streams[name]['pendingSampleTruncated']=observed<int(group.get('pending') or 0)
        result['streams']=streams
        logs=[(mid,pairs(v)) for mid,v in c.command('XREVRANGE',prefix+':logs','+','-','COUNT',config['log_limit'])]
        logs=[(mid,log) for mid,log in logs if reportable_worker(log.get('worker'))]
        # Decode a small set of closest lease entries, including historical log consumers.
        observed_consumers={r.get('consumer') for r in registry.values()}
        latest_log_consumers={}
        for _,log in logs:
            identity=(log.get('computer'),log.get('worker'))
            if identity not in latest_log_consumers:latest_log_consumers[identity]=log.get('consumer')
        observed_consumers.update(latest_log_consumers.values())
        for consumer in observed_consumers:
            for lease in sorted(pending_by_worker.get(consumer,[]),key=lambda p:p['leaseIdleMs'])[:3]:
                entries=c.command('XRANGE',lease['streamKey'],lease['messageId'],lease['messageId'],'COUNT',1) or []
                payload=json_value(pairs(entries[0][1]).get('payload')) if entries else {}
                lease.update(taskId=payload.get('task_id'),keyword=payload.get('keyword'),fingerprint=payload.get('fingerprint'))
        errors=[]
        for mid,log in logs:
            name=log.get('worker');computer=log.get('computer');consumer=log.get('consumer')
            if not name:continue
            stamp=log.get('timestamp');dt=parse_time(stamp)
            if not dt:continue
            wk=(computer or 'unknown')+'/'+name
            msg=log.get('message','');event=log.get('event','')
            evidence=event+' '+msg
            if dt>now-timedelta(hours=1) and any(token in evidence for token in ('redis_heartbeat_failed','redis_lease_lost','ECONNRESET','MySQL import failed','redis_worker_error')):
                errors.append({'time':stamp,'worker':wk,'kind':'redis_connection' if 'redis_' in evidence else 'mysql_import','event':event})
        result['workers']=worker_states(registry,acks,logs,pending_by_worker,now,config,result['generation'])
        result['recentErrors']=errors[:30]
        try:result['productionOutputs']=read_outputs(c,prefix,result['generation'],now)
        except Exception:
            result['productionOutputs']={'available':False,'hourly':None,'latest':[],'reason':'telemetry_source_unavailable'}
        for output in result['productionOutputs']['latest']:
            target=next((w for w in result['workers'] if w.get('computer')==output.get('computer') and w.get('worker')==output.get('worker')),None)
            if target is None:
                target={'computer':output.get('computer'),'worker':output.get('worker'),'observation':'verified_output_only','lastHeartbeatAt':None,'currentKeyword':None}
                result['workers'].append(target)
            for field in ('lastEffectiveOutputAt','lastMetadataAt','lastSubtitleAt','lastCommentAt'):
                target[field]=output.get(field)
            target['effectiveOutputEvidence']='mysql_commit_ack_and_readback_verified'
            target['telemetryStatus']='verified_output_observed'
        result['phaseEfficiency']=phase_metrics(logs,now)
        history_path=ROOT/'output/progress-history.json'
        try:history=json.loads(history_path.read_text(encoding='utf-8'))
        except (OSError,ValueError):history=[]
        result['progressEfficiency'],history=progress_rate(history,result,now,result['workers'],config)
        atomic_json(history_path,history)
        result['logSample']={'limit':config['log_limit'],'count':len(logs),'oldestAt':logs[-1][1].get('timestamp') if logs else None}
        result['warnings']+=['进度为Redis任务与断点口径，尚非数据库完整性审计。','机器注册心跳与任务租约分开；停止机器的遗留pending不代表仍在执行。','Redis扫描非事务快照，活跃任务数字可能在读取期间变化。']
    return result

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--config',type=Path,default=ROOT/'config.json');p.add_argument('--output',type=Path,default=ROOT/'output/redis.json');a=p.parse_args()
    try:result=collect(json.loads(a.config.read_text(encoding='utf-8-sig')))
    except Exception as e:
        result={'generatedAt':datetime.now(timezone.utc).isoformat(),'sources':{'redis':'unavailable'},'errorType':type(e).__name__,'warnings':['Redis不可用，不能将缺少数据解读为零任务。']}
    atomic_json(a.output,result);print(json.dumps({'output':str(a.output),'redis':result['sources']['redis']},ensure_ascii=False))
