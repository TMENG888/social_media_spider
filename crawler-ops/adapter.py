"""Read-only monitoring adapter, isolated from existing notification schedules."""
import sys, json, time, subprocess, importlib.util
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor
from settings import *
from keyword_progress import observe as keyword_observe, enrich as keyword_enrich, unavailable as keyword_unavailable
sys.dont_write_bytecode=True
sys.path.insert(0,str(MONITOR))
from collect import RedisConnection
spec=importlib.util.spec_from_file_location('ops_existing_relay',MONITOR/'incident-relay.py')
relay=importlib.util.module_from_spec(spec);spec.loader.exec_module(relay)
BJ=timezone(timedelta(hours=8))

def timestamp(v):
    try:
        if isinstance(v,(int,float)):return v/1000 if v>1e12 else v
        dt=datetime.fromisoformat(str(v).replace('Z','+00:00'))
        return dt.replace(tzinfo=BJ).timestamp() if dt.tzinfo is None else dt.timestamp()
    except (ValueError,TypeError):return None

def json_records(raw):
    found=[]
    for v in raw or []:
        try:r=json.loads(v)
        except (ValueError,TypeError):continue
        if isinstance(r,dict):found.append(r)
    return found

def child(mode, *args, data=None, timeout=22):
    try:
        p=subprocess.run([str(PYTHON),'-B',str(BASE/'probe.py'),mode,*args],input=json.dumps(data) if data is not None else None,capture_output=True,text=True,encoding='utf-8',timeout=timeout)
        return json.loads(p.stdout.lstrip('\ufeff'))
    except (subprocess.TimeoutExpired,ValueError,OSError):
        return {'state':'unavailable','message':'远程读取或执行超时；未确认成功。'}

def accepted_events(events,campaign,now):
    seen=set();out=[]
    day=datetime.fromtimestamp(now,BJ).replace(hour=0,minute=0,second=0,microsecond=0).timestamp()
    for e in events:
        if e.get('projects') != PROJECTS: continue
        at=timestamp(e.get('committedAt'))
        if e.get('campaign')!=campaign or e.get('deploymentTest') or not e.get('readbackVerified') or at is None or not day<=at<=now:continue
        if not e.get('eventId') or e['eventId'] in seen:continue
        if any(type(e.get(k)) is not int or e[k]<0 for k in ('newPosts','videoContentWrites')):continue
        seen.add(e['eventId']);out.append(e)
    return out

def output(events,now,computer=None,worker=None):
    if computer:events=[e for e in events if e.get('computer','').upper()==computer.upper() and e.get('worker')==worker]
    if not events:return {'hour':None,'day':None,'batches':0}
    return dict(hour=sum(e['newPosts'] for e in events if timestamp(e['committedAt'])>=now-3600),day=sum(e['newPosts'] for e in events),batches=len(events),lastAt=max(e['committedAt'] for e in events))

def redis_state(source):
    name,ns,url,password=source
    result={'name':name,'source':'unavailable','workers':[],'events':[],'holds':[],'sampledAt':None}
    try:
        if not password:raise ValueError('CREDENTIAL_UNAVAILABLE')
        with RedisConnection(url,password,timeout=4) as c:
            sec,micro=c.command('TIME');now=int(sec)+int(micro)/1e6
            result['sampledAt']=now;result['clockSkew']=abs(now-time.time())>10
            campaign=ns.split('{',1)[1].split('}',1)[0]
            result['workers']=[w for w in json_records(c.command('HVALS',ns+':monitor:workers')) if w.get('campaign')==campaign and not w.get('deploymentTest')]
            result['holds']=json_records(c.command('HVALS',ns+':control:stop-requests'))
            start=datetime.fromtimestamp(now,BJ).replace(hour=0,minute=0,second=0,microsecond=0).astimezone(timezone.utc)
            end=datetime.fromtimestamp(now,timezone.utc);events=[]
            while start<=end:
                events+=json_records(c.command('HVALS',ns+':monitor:commits:'+start.strftime('%Y%m%d%H')))
                start+=timedelta(hours=1)
            result['events']=accepted_events(events,campaign,now)
            try:
                result['incidents']=json_records(c.command('HVALS',ns+':monitor:incidents'))
                result['restrictionsSource']='ok'
            except Exception:result['restrictionsSource']='unavailable'
            try:result['keywords']=keyword_observe(c,ns,name,now)
            except Exception as e:result['keywords']={**keyword_unavailable(name),'errorType':type(e).__name__}
            result['source']='ok'
    except Exception as e:result['errorType']=type(e).__name__
    return result

def database(date_requests=None):
    try:
        p=subprocess.run([str(NODE),str(BASE/'metrics.mjs'),str(PACKAGE/'小红书/common')],input=json.dumps(date_requests or []),capture_output=True,text=True,encoding='utf-8',timeout=45)
        return json.loads(p.stdout)
    except (ValueError,OSError,subprocess.TimeoutExpired):return {'source':'unavailable','at':datetime.now(timezone.utc).isoformat()}

def inventory(rows,field):
    return {name:sum(int(r.get('n',0)) for r in rows if r.get('platform')==name and r.get('project') in PROJECTS) for name in PLATFORMS.values()}

def historic_snapshot(path):
    v=read_json(path,{})
    if v.get('source')!='live_mysql_read_only_consistent_snapshot':return None
    result={'at':v.get('queried_at'),'posts':{},'comments':{}}
    for field,src in [('posts','post_stats'),('comments','comment_stats')]:
        result[field]={name:sum(int(r.get('rows',0)) for r in v.get(src,[]) if r.get('platform')==name and r.get('project') in PROJECTS) for name in PLATFORMS.values()}
    return result

def inventory_deltas(db,now):
    if db.get('source')!='ok':return {'source':'unavailable'}
    at=timestamp(db['at']);day=datetime.fromtimestamp(at,BJ).replace(hour=0,minute=0,second=0,microsecond=0).timestamp()
    current={'at':db['at'],'posts':inventory(db['posts'],'posts'),'comments':inventory(db['comments'],'comments')}
    history=OUTPUT/'inventory-topic1';history.mkdir(exist_ok=True)
    (history/(datetime.fromtimestamp(at,timezone.utc).strftime('%Y%m%dT%H%M%S')+'.json')).write_text(json.dumps(current,ensure_ascii=False),encoding='utf-8')
    candidates=[]
    for p in history.glob('*.json'):
        r=read_json(p,{})
        if timestamp(r.get('at')) is not None:candidates.append(r)
    # Existing hourly snapshots seed this independent module without changing them.
    old=HISTORY_ROOT
    for date in {datetime.fromtimestamp(day,BJ).strftime('%Y%m%d'),datetime.fromtimestamp(day-3600,BJ).strftime('%Y%m%d')}:
        for folder in old.glob(date+'_*'):
            r=historic_snapshot(folder/'live_stats.json')
            if r:candidates.append(r)
    def closest(target,tolerance):
        options=[r for r in candidates if timestamp(r.get('at')) is not None and timestamp(r['at'])<=at and abs(timestamp(r['at'])-target)<=tolerance]
        return min(options,key=lambda r:abs(timestamp(r['at'])-target)) if options else None
    result={'source':'ok','at':db['at'],'totals':current,'hour':None,'day':None,'brands':db.get('brands',{'source':'unavailable'})}
    for label,target,tol in [('hour',at-3600,600),('day',day,300)]:
        base=closest(target,tol)
        if base:
            result[label]={'start':base['at'],'end':db['at'],'minutes':round((at-timestamp(base['at']))/60,1),'values':{name:{f:current[f][name]-base[f][name] for f in ('posts','comments')} for name in PLATFORMS.values()}}
    return result

def classify(h,now,login,source_ok):
    if not source_ok:return 'unknown','心跳读取失败'
    if not h:return 'stale','未读到心跳'
    at=timestamp(h.get('lastSeenAt'))
    if at is None:return 'unknown','心跳时间无效'
    age=now-at
    if age < -10:return 'unknown','机器时钟异常'
    if age>30:return 'stale','心跳已过期'
    if login.get('fresh') and login.get('phase') not in ('verified','cancelled','unavailable',None):return 'verification','等待登录／验证'
    return {'collecting':('collecting','采集中'),'resting':('resting','原位休息'),'cooldown':('cooldown','安全冷却'),'starting':('waiting','正在启动'),'waiting':('waiting','在线等待'),'stopped':('stopped','已停止')}.get(h.get('state'),('unknown','状态待核实'))

def with_activity(state,label,row,now):
    activity=row.get('activity') or {}
    if row.get('finishedAt') and (row.get('state') or {}).get('state')=='stopped':return 'stopped','已停止'
    if state not in ('stale','unknown') or row.get('finishedAt'):return state,label
    fg=timestamp((activity.get('foreground') or {}).get('at'))
    bg=timestamp((activity.get('persistence') or {}).get('at'))
    if fg is not None and 0<=now-fg<=90:return 'collecting','采集中'
    if bg is not None and 0<=now-bg<=90:return 'background','后台处理中'
    return state,'采集状态待核实' if state=='stale' else label

def article_date_progress(keyword,dates,verified):
    if not keyword:return {'source':'empty','latestCollectedPublishedAt':None,'earliestImportedPublishedAt':None}
    if dates.get('keyword')!=keyword:
        return {'source':'unavailable','keyword':keyword,'errorType':dates.get('errorType') or 'DATE_KEYWORD_MISMATCH',
                'latestCollectedPublishedAt':None,'earliestImportedPublishedAt':None}
    return {**dates,'databaseSource':verified.get('source') if verified else 'unavailable',
            'earliestImportedPublishedAt':verified.get('earliestImportedPublishedAt') if verified else None,
            'verifiedPosts':verified.get('verifiedPosts') if verified else None,
            'databaseErrorType':verified.get('errorType') if verified else 'DATE_DATABASE_RESULT_MISSING'}

def audit_article_dates(rows):
    """Bounded panel-only diagnostics; never log content, credentials or article IDs."""
    try:
        target=OUTPUT/'article-date-observations.jsonl'
        if target.exists() and target.stat().st_size>2_000_000:target.replace(OUTPUT/'article-date-observations.previous.jsonl')
        fields=('source','databaseSource','errorType','databaseErrorType','taskId','collectionPass',
                'latestCollectedPublishedAt','earliestImportedPublishedAt','latestCollectedAt','localPosts','verifiedPosts')
        observation=dict(at=time.time(),rows=[dict(machine=r['machine'],platform=r['platform'],keyword=r.get('keyword'),
            **{k:(r.get('dateProgress') or {}).get(k) for k in fields}) for r in rows])
        with target.open('a',encoding='utf-8') as f:f.write(json.dumps(observation,ensure_ascii=False)+'\n')
    except OSError:pass

def collect():
    started=time.time()
    with ThreadPoolExecutor(max_workers=11) as pool:
        fs={m['label']:pool.submit(child,'files',m['label']) for m in MACHINES}
        restriction_files={m['label']:pool.submit(child,'restrictions',m['label']) for m in MACHINES}
        rs={}
        try:
            for src in relay.sources(include_channels=False):rs[src[0]]=pool.submit(redis_state,src)
        except Exception:pass
        file_rows={k:f.result() for k,f in fs.items()}
        date_requests=[]
        for label,items in file_rows.items():
            for row in items if isinstance(items,list) else []:
                dates=row.get('dateProgress') or {}
                ids=dates.pop('_postIds',[])
                if dates.get('source') in ('ok','empty'):
                    date_requests.append(dict(machine=label,platform=row['platform'],keyword=row.get('keyword'),ids=ids,taskId=dates.get('taskId'),collectionPass=dates.get('collectionPass')))
        dbf=pool.submit(database,date_requests)
        redis={k:f.result() for k,f in rs.items()};db=dbf.result()
        restriction_results={k:f.result() for k,f in restriction_files.items()}
    try:
        from restriction_timeline import update as update_restrictions
        restriction_meta=update_restrictions(redis,restriction_results)
    except Exception as e:restriction_meta={'source':'unavailable','errorType':type(e).__name__}
    rows=[];platforms=[];warnings=[]
    channel_rows=read_json(OUTPUT/'channels-readonly.json',[]) or []
    for kind,name in PLATFORMS.items():
        r=redis.get(name,{'source':'unavailable','workers':[],'events':[],'holds':[]});now=r.get('sampledAt') or time.time()
        platforms.append(dict(key=kind,name=name,output=output(r['events'],now),source=r['source']))
        if r['source']!='ok':warnings.append(name+'：无法读取独立心跳与入库流水。')
        for m in MACHINES:
            fr=file_rows[m['label']];row=next((x for x in fr if x['platform']==kind),{}) if isinstance(fr,list) else {}
            h=next(iter(sorted([x for x in r['workers'] if x.get('computer','').upper()==m['computer'].upper() and x.get('worker')==worker(m,kind)],key=lambda x:timestamp(x.get('lastSeenAt')) or 0,reverse=True)),{})
            login=row.get('login',{});state,label=classify(h,now,login,r['source']=='ok')
            row['heartbeatStatus']=state if state in ('stale','unknown') else 'fresh'
            state,label=with_activity(state,label,row,now)
            planned=False
            if planned:state,label='planned','已安排停采'
            row.update(id=m['label']+'-'+kind,machine=m['label'],computer=m['computer'],worker=worker(m,kind),platform=kind,status=state,statusLabel=label,heartbeatAt=h.get('lastSeenAt'),heartbeatAge=now-(timestamp(h.get('lastSeenAt')) or now),resumeAt=h.get('resumeAt'),fileSource=row.get('fileSource','unavailable'),output=output(r['events'],now,m['computer'],worker(m,kind)),plannedStop=planned)
            if row.get('finishedAt') and state in ('cooldown','waiting','resting') and not login.get('fresh'):
                row.update(previousKeyword=row.get('keyword'),previousTopics=row.get('topics'),keyword=None,topics=row.get('scope',[]),awaitingTask=True)
            dates=row.get('dateProgress') or {'source':'unavailable'}
            verified=next((d for d in db.get('articleDates',[]) if d.get('machine')==m['label'] and d.get('platform')==kind and d.get('keyword')==row.get('keyword') and d.get('taskId')==dates.get('taskId') and d.get('collectionPass')==dates.get('collectionPass')),None)
            row['dateProgress']=article_date_progress(row.get('keyword'),dates,verified)
            if row['heartbeatStatus'] in ('stale','unknown') and not planned:
                row['output']['partial']=True
                if row['output']['hour']==0:row['output']['hour']=None
            row['remoteHold']=any(x.get('target')==m['computer'].upper()+'/'+worker(m,kind) for x in r.get('holds',[]))
            channel=next((c.get('result',{}) for c in channel_rows if c.get('machine')==m['label']),{})
            row['remoteChannel']='unavailable' if channel.get('state')=='unavailable' else 'available' if channel.get('computer')==m['computer'] else 'unchecked'
            row['canRecover']=kind=='xhs' and state in ('stale','stopped') and not row['remoteHold'] and not row.get('stops') and row['fileSource']=='ok'
            rows.append(row)
    keywords={kind:keyword_enrich(redis.get(name,{}).get('keywords') or keyword_unavailable(name),[m for m in rows if m['platform']==kind]) for kind,name in PLATFORMS.items()}
    audit_article_dates(rows)
    return dict(schema=3,activeTopic=ACTIVE_TOPIC,collectionMode='文章＋评论',sampledAt=time.time(),startedAt=started,interval=INTERVAL,machines=rows,platforms=platforms,keywords=keywords,database=inventory_deltas(db,time.time()),warnings=warnings,restrictions=restriction_meta)
