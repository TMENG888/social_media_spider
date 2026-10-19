"""Read-only worker evidence; lease ownership is not a liveness heartbeat."""
import json
from datetime import datetime, timezone, timedelta
from worker_visibility import reportable_worker

def stamp(value):
    try:
        dt=datetime.fromisoformat(value.replace('Z','+00:00'))
        # Historical collector timestamps without offset are Beijing local time.
        if dt.tzinfo is None:dt=dt.replace(tzinfo=timezone(timedelta(hours=8)))
        return dt.astimezone(timezone.utc)
    except (ValueError,AttributeError,TypeError):return None

def worker_states(registry,acks,logs,pending,now,config,generation):
    newest={};workers={}
    for r in registry.values():
        if not reportable_worker(r.get('worker')):continue
        if not r.get('worker') or not r.get('computer'):continue
        if r.get('generation') and r['generation']!=generation:continue
        key=(r['computer'],r['worker'])
        if key not in newest or (stamp(r.get('lastSeenAt')) or datetime.min.replace(tzinfo=timezone.utc))>(stamp(newest[key].get('lastSeenAt')) or datetime.min.replace(tzinfo=timezone.utc)):
            newest[key]=r
    for _,log in logs:
        if not reportable_worker(log.get('worker')):continue
        key=(log.get('computer') or 'unknown',log.get('worker'))
        if not key[1] or not stamp(log.get('timestamp')):continue
        w=workers.setdefault(key,{'computer':key[0],'worker':key[1],'consumer':log.get('consumer'),'lastLogAt':log.get('timestamp'),'lastObservedKeyword':log.get('keyword') or None,'lastEffectiveOutputAt':None})
        if not w.get('lastObservedKeyword') and log.get('keyword'):w['lastObservedKeyword']=log['keyword']
    for key,r in newest.items():
        w=workers.setdefault(key,{'computer':key[0],'worker':key[1],'lastEffectiveOutputAt':None})
        dt=stamp(r.get('lastSeenAt'));age=(now-dt).total_seconds() if dt else None
        status=r.get('controlStatus');consumer=r.get('consumer')
        ack=acks.get(consumer,{})
        if status=='stopped':state='stopped'
        elif age is not None and age < -60:state='clock_skew'
        elif age is None or age>config.get('heartbeat_stale_seconds',30):state='heartbeat_stale'
        elif status=='draining':state='draining'
        elif status=='exit_unconfirmed':state='exit_unconfirmed'
        elif r.get('taskId') and r.get('taskStatus')=='running':state='executing'
        else:state='online_waiting'
        w.update(consumer=consumer,pid=r.get('pid'),registrationObserved=True,observation=state,
                 lastHeartbeatAt=r.get('lastSeenAt'),heartbeatAgeSeconds=round(age,1) if age is not None else None,
                 controlStatus=status,taskId=r.get('taskId'),taskStatus=r.get('taskStatus'),
                 currentKeyword=r.get('keyword') if state in ('executing','draining') else None,
                 taskStartedAt=r.get('startedAt'),taskKind=r.get('taskKind'),
                 stopAckStatus=ack.get('status'),stopAckAt=ack.get('observedAt'),stopCommandId=ack.get('commandId'))
        own=pending.get(consumer,[])
        limit=r.get('leaseReclaimSeconds') or config.get('lease_reclaim_seconds',300)
        own=sorted(own,key=lambda p:p['leaseIdleMs'])
        w['pendingLeaseCount']=len(own)
        w['leases']=[{**p,'lastTouchAt':(now-timedelta(milliseconds=p['leaseIdleMs'])).isoformat(),
                      'reclaimAfterSeconds':limit,'reclaimThresholdSource':'worker_registry' if r.get('leaseReclaimSeconds') else 'monitor_default',
                      'reclaimEligible':p['leaseIdleMs']>=limit*1000} for p in own[:3]]
        w['lastLeaseTouchAt']=w['leases'][0]['lastTouchAt'] if own else None
        w['leaseInterpretation']='stopped_pending_reclaim' if state=='stopped' and own else 'pending_is_not_heartbeat'
        # Registry is authoritative: a stopped process is never current merely because a PEL entry remains.
        w['telemetryStatus']='registered_no_verified_output'
        current_logs=[log for _,log in logs if log.get('consumer')==consumer and stamp(log.get('timestamp'))]
        w['lastLogAt']=current_logs[0].get('timestamp') if current_logs else None
        if not w.get('taskKind') and own and state in ('executing','draining'):
            w['taskKind']='video_retry' if own[0]['stream']!='tasks' else 'primary'
    for key,w in workers.items():
        owned=pending.get(w.get('consumer'),[])
        w['pendingKeywordTasks']=sum(p.get('stream')=='tasks' for p in owned)
        w['pendingVideoRetryTasks']=sum(p.get('stream') in ('video-retry','retry-round') for p in owned)
        w['pendingUnclassifiedTasks']=len(owned)-w['pendingKeywordTasks']-w['pendingVideoRetryTasks']
        if key not in newest:
            own=sorted(pending.get(w.get('consumer'),[]),key=lambda p:p['leaseIdleMs'])
            limit=config.get('lease_reclaim_seconds',300)
            w.update(registrationObserved=False,observation='registration_unobserved',lastHeartbeatAt=None,currentKeyword=None,
                     lastLeaseTouchAt=(now-timedelta(milliseconds=own[0]['leaseIdleMs'])).isoformat() if own else None,
                     leases=[{**p,'lastTouchAt':(now-timedelta(milliseconds=p['leaseIdleMs'])).isoformat(),
                              'reclaimAfterSeconds':limit,'reclaimThresholdSource':'monitor_default','reclaimEligible':p['leaseIdleMs']>=limit*1000} for p in own[:3]],
                     pendingLeaseCount=len(own),telemetryStatus='no_verified_output')
    for name in config['expected_workers']:
        if not reportable_worker(name):continue
        if not any(w['worker']==name for w in workers.values()):
            workers[('unknown',name)]={'worker':name,'computer':'unknown','registrationObserved':False,'observation':'registration_unobserved','currentKeyword':None,'lastHeartbeatAt':None,'lastEffectiveOutputAt':None,'leases':[]}
    return list(workers.values())

def phase_metrics(logs,now):
    samples=[];seen=set();starts={};task_samples=[]
    for mid,log in reversed(logs):
        if not reportable_worker(log.get('worker')):continue
        dt=stamp(log.get('timestamp'))
        if not dt or not now-timedelta(hours=1)<=dt<=now:continue
        event=log.get('event');data=log
        if event=='worker_output':
            try:data=json.loads(log.get('message',''))
            except (ValueError,TypeError):continue
            if not isinstance(data,dict):continue
            event=data.get('event')
        identity=(log.get('consumer'),log.get('taskId'),log.get('messageId'),log.get('taskKind'))
        if event=='task_started':starts[identity]=dt
        if event=='task_finished' and identity in starts:
            seconds=(dt-starts.pop(identity)).total_seconds()
            if seconds>=0:task_samples.append({'seconds':seconds,'worker':log.get('worker'),'kind':log.get('taskKind')})
        if event not in ('persistent_asr_request_complete','client_audio_asr_queued'):continue
        key=(log.get('consumer'),event,data.get('id') or data.get('wav_path') or mid)
        if key in seen:continue
        seen.add(key)
        samples.append({'event':event,'worker':log.get('worker'),'seconds':data.get('elapsed_seconds') if event=='persistent_asr_request_complete' else data.get('recorded_seconds'),
                        'audioSeconds':data.get('duration_seconds'),'textLength':data.get('text_length'),
                        'productionAccepted':data.get('quality',{}).get('accepted') if isinstance(data.get('quality'),dict) else None})
    asr=[s for s in samples if s['event']=='persistent_asr_request_complete' and isinstance(s['seconds'],(int,float))]
    recording=[s for s in samples if s['event']=='client_audio_asr_queued' and isinstance(s['seconds'],(int,float))]
    return {'windowMinutes':60,'asrSamples':len(asr),'averageAsrSeconds':round(sum(s['seconds'] for s in asr)/len(asr),2) if asr else None,
            'asrProductionAccepted':sum(s['productionAccepted'] is True for s in asr),'recordingSamples':len(recording),
            'averageRecordingSeconds':round(sum(s['seconds'] for s in recording)/len(recording),2) if recording else None,
            'taskSamples':len(task_samples),'averageTaskSeconds':round(sum(s['seconds'] for s in task_samples)/len(task_samples),2) if task_samples else None,
            'samples':samples[-20:],'note':'Bounded centralized log samples; ASR/recording/task elapsed time is not complete per-video end-to-end time or DB success.'}

def progress_rate(history,snapshot,now,workers,config):
    generation=snapshot.get('generation');counts=snapshot.get('videos',{}).get('checkpointStates',{})
    current={'at':now.isoformat(),'generation':generation,'completed':counts.get('completed',0),'known':sum(counts.values())}
    kept=[r for r in history if r.get('generation')==generation and stamp(r.get('at')) and now-timedelta(hours=24)<=stamp(r['at'])<now]
    window=[r for r in kept if stamp(r['at'])>=now-timedelta(hours=1)]
    baseline=window[0] if window else None
    seconds=(now-stamp(baseline['at'])).total_seconds() if baseline else 0
    delta=current['completed']-baseline['completed'] if baseline else 0
    rate=delta*3600/seconds if seconds>0 and delta>=0 else None
    # Includes dead letters/reviews: they still prevent genuinely complete collection.
    remaining=sum(n for state,n in counts.items() if state!='completed')
    active=sum(w.get('observation') in ('executing','online_waiting') for w in workers)
    reason=None
    if not active:reason='no_confirmed_active_worker'
    elif delta<0:reason='checkpoint_count_decreased'
    elif seconds<config.get('eta_min_window_seconds',900):reason='observation_window_too_short'
    elif delta<config.get('eta_min_completed',5) or not rate:reason='insufficient_net_completions'
    eta=[round(remaining/rate*0.7,1),round(remaining/rate*1.5,1)] if not reason and remaining else None
    return {'windowSeconds':round(seconds),'netCompleted':delta if baseline else None,'netCompletedPerHour':round(rate,2) if rate is not None else None,
            'knownRemaining':remaining,'activeWorkers':active,'knownBacklogEtaHours':eta,'etaUnavailableReason':reason,
            'scope':'net checkpoint progress; ETA only for currently known videos, excluding new keyword discoveries; empirical scenario range, not confidence interval'},kept[-1439:]+[current]
