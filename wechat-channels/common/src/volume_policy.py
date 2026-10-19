"""Quantity-only keyword acceptance. Never invent/seed a replacement task.

The positive-keyword P80 is frozen per configured generation. SQL is the only
source of post counts; subtitles/scan endpoints are explicitly not certified.
Original stream messages and all video checkpoints remain retained.
"""
import json
import os
import re
import secrets
import signal
import shutil
import subprocess
import sys
import time
from operational_gate import OperationalGate
from database_diagnostics import observe as observe_database, safe_code
from reset_once import ResetOncePolicy, POLICY as RECOLLECT_POLICY
from datetime import datetime
from pathlib import Path

POLICY = '20261015-keyword-count-p80-v1'


def _database_observation(common, payload, code=None, stage='unknown'):
    try:
        return observe_database(common, payload, code, stage)
    except Exception:
        # Monitoring must not erase the original failure or expose raw stderr.
        print(json.dumps({'event':'database_monitor_local_write_failed',
                          'errorCode':'MONITOR_LOCAL_STATE_FAILED'}), flush=True)


def bridge(common, payload):
    node = Path(common)/'runtime'/'node'/'node.exe'
    executable = str(node) if node.is_file() else shutil.which('node')
    if not executable:
        _database_observation(common, payload, 'VOLUME_NODE_MISSING', 'runtime')
        raise RuntimeError('VOLUME_NODE_MISSING')
    try:
        process = subprocess.run([executable, str(Path(common)/'src'/'volume-db-readback.mjs')],
            input=json.dumps(payload, ensure_ascii=False), capture_output=True, text=True,
            encoding='utf-8', errors='replace', timeout=180, env=os.environ.copy(),
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    except subprocess.TimeoutExpired:
        _database_observation(common, payload, 'VOLUME_DATABASE_READBACK_TIMEOUT', 'query')
        raise RuntimeError('VOLUME_DATABASE_READBACK_FAILED:VOLUME_DATABASE_READBACK_TIMEOUT') from None
    except OSError:
        _database_observation(common, payload, 'VOLUME_NODE_EXEC_FAILED', 'runtime')
        raise RuntimeError('VOLUME_DATABASE_READBACK_FAILED:VOLUME_NODE_EXEC_FAILED') from None
    if process.returncode:
        detail = {}
        for line in (process.stderr or '').splitlines():
            try:
                candidate = json.loads(line)
                if isinstance(candidate, dict):
                    detail = candidate
            except ValueError:
                pass
        code = safe_code(detail.get('errorCode'))
        stage = detail.get('stage', 'unknown')
        if not detail and 'ERR_MODULE_NOT_FOUND' in (process.stderr or ''):
            code, stage = 'NODE_DEPENDENCY_MISSING', 'runtime'
        elif not detail and 'MODULE_NOT_FOUND' in (process.stderr or ''):
            code, stage = 'NODE_MODULE_LOAD_FAILED', 'runtime'
        _database_observation(common, payload, code, stage)
        raise RuntimeError('VOLUME_DATABASE_READBACK_FAILED:'+code)
    try:
        result = json.loads(process.stdout)
        if not isinstance(result, dict):
            raise ValueError('invalid response')
    except (ValueError, TypeError):
        _database_observation(common, payload, 'VOLUME_READBACK_INVALID_RESPONSE', 'response')
        raise RuntimeError('VOLUME_DATABASE_READBACK_FAILED:VOLUME_READBACK_INVALID_RESPONSE') from None
    if payload.get('operation') != 'validate' and result.get('dbReadbackVerified') is True:
        _database_observation(common, payload)
    return result


TRANSITION = """
local stream,status,history,tokens,tries=KEYS[1],KEYS[2],KEYS[3],KEYS[4],KEYS[5]
redis.call('HGET',status,'__probe__');redis.call('HGET',history,'__probe__')
redis.call('HGET',tokens,'__probe__');redis.call('HGET',tries,'__probe__')
local id,mid,group,consumer,generation,token,mode=ARGV[1],ARGV[2],ARGV[3],ARGV[4],ARGV[5],ARGV[6],ARGV[7]
local d=cjson.decode(ARGV[8]);local task=cjson.decode(ARGV[9]);local idle=tonumber(ARGV[10])
local annual=cjson.decode(ARGV[15] or 'null')
local clock=redis.call('TIME');local now=tonumber(clock[1])*1000+math.floor(tonumber(clock[2])/1000)
if d.policy~='20261015-keyword-count-p80-v1' or d.taskId~=id or d.platform~='微信视频号'
 or d.keyword~=task.keyword or d.projectName~=ARGV[13] or d.dbReadbackVerified~=true
 or d.qualityVerified~=false or d.subtitleQualityRequired~=false
 or type(d.posts)~='number' or d.posts<0 or d.posts~=math.floor(d.posts)
 or type(d.threshold)~='number' or d.threshold<1 or d.threshold~=math.floor(d.threshold)
 or now-tonumber(ARGV[11])>60000 or tonumber(ARGV[11])>now+1000 then
 return redis.error_reply('VOLUME_EVIDENCE_INVALID') end
local rows=redis.call('XRANGE',stream,mid,mid)
if #rows~=1 then return redis.error_reply('VOLUME_ORIGINAL_MESSAGE_MISSING') end
local payload=nil
for i=1,#rows[1][2],2 do if rows[1][2][i]=='payload' then payload=rows[1][2][i+1] end end
local original=cjson.decode(payload or '{}')
if original.task_id~=id or original.topic~=task.topic or original.keyword~=task.keyword then
 return redis.error_reply('VOLUME_ORIGINAL_IDENTITY_MISMATCH') end
local pending=redis.call('XPENDING',stream,group,mid,mid,1)
if mode=='finish' then
 if #pending~=1 or pending[1][2]~=consumer or redis.call('HGET',tokens,id)~=token then
  return redis.error_reply('VOLUME_LEASE_LOST') end
elseif mode=='delivered' then
 if #pending~=1 or pending[1][2]~=consumer then return redis.error_reply('VOLUME_LEASE_LOST') end
elseif #pending==1 and tonumber(pending[1][3])<idle then
 return cjson.encode({status='busy',changed=false}) end
if #pending==0 then
 local last=nil
 for _,g in ipairs(redis.call('XINFO','GROUPS',stream)) do
  local name,lid=nil,nil
  for i=1,#g,2 do if g[i]=='name' then name=g[i+1] elseif g[i]=='last-delivered-id' then lid=g[i+1] end end
  if name==group then last=lid end
 end
 if not last then return redis.error_reply('VOLUME_GROUP_MISSING') end
 local ma,mb=string.match(mid,'^(%d+)%-(%d+)$');local la,lb=string.match(last,'^(%d+)%-(%d+)$')
 if tonumber(ma)>tonumber(la) or (tonumber(ma)==tonumber(la) and tonumber(mb)>tonumber(lb)) then
  -- FORCE on an unread message would allow a second healthy worker to read
  -- the same message with >. Use the group's sequential delivery instead.
  return cjson.encode({status='unread_requires_sequential_delivery',changed=false})
 end
end
local field=id..'|'..generation
local old=redis.call('HGET',status,id)
local count=tonumber(redis.call('HGET',tries,field)) or 0
local exhausted_field=field..'|retry-exhausted-completion'
local exhausted_ledger=redis.call('HGET',history,exhausted_field)
if old and exhausted_ledger then
 local a=cjson.decode(exhausted_ledger);local r=cjson.decode(old)
 if a.completedResult==old and a.generation==generation and a.snapshotId==d.snapshotId
  and r.status=='completed' and r.acceptedBy=='retry_exhausted_completion' and r.quantityAccepted==false then
  return cjson.encode({status='completed',changed=false,acceptedByExhaustion=true,acceptedByVolume=false}) end
end
local manual_ledger=redis.call('HGET',history,field..'|user-approved-completion')
if old and manual_ledger then
 local a=cjson.decode(manual_ledger);local r=cjson.decode(old)
 local u=r.userCompletion
 if a.completedResult==old and a.generation==generation and r.status=='completed'
  and r.accepted==true and r.acceptedBy=='user_approved_completion'
  and r.quantityAccepted==false and type(u)=='table'
  and u.policy=='20261016-user-approved-exact-original-v1'
  and u.taskId==id and u.messageId==mid and u.keyword==task.keyword
  and u.stopFurtherRetries==true and u.authorizationScope=='exact_original_only' then
  return cjson.encode({status='completed',changed=false,acceptedByUser=true,acceptedByVolume=false}) end
end
local annual_field=field..'|annual-search-completion'
local annual_ledger=redis.call('HGET',history,annual_field)
if d.posts<d.threshold and old and annual_ledger then
 local a=cjson.decode(annual_ledger);local r=cjson.decode(old)
 if a.completedResult==old and a.generation==generation and r.status=='completed'
  and r.acceptedBy=='verified_low_year_search' and r.quantityAccepted==false
  and type(r.annualAcceptance)=='table' and r.annualAcceptance.snapshotId==d.snapshotId then
  return cjson.encode({status='completed',changed=false,acceptedByAnnual=true,acceptedByVolume=false}) end
end
local annual_ok=type(annual)=='table' and annual.ok==true
if annual_ok then
 if mode~='finish' or annual.policy~='20261016-keyword-p80-or-low-year-v2'
  or annual.taskId~=id or annual.snapshotId~=d.snapshotId or annual.keyword~=task.keyword
  or annual.projectName~=d.projectName or annual.posts~=d.posts or annual.threshold~=d.threshold
  or annual.retryUnit~='original_keyword' or annual.quantityAccepted~=false
  or annual.subtitleQualityRequired~=false or type(annual.checkedAtMs)~='number'
  or now-annual.checkedAtMs>60000 or annual.checkedAtMs>now+1000
  or type(annual.annualAvailableUpperBound)~='number' or annual.annualAvailableUpperBound>=d.threshold
  or annual.annualAvailableUpperBound<d.posts or annual.databaseCoverageLowerBound<0.8 then
  return redis.error_reply('ANNUAL_EVIDENCE_INVALID') end
 if annual_ledger then return redis.error_reply('ANNUAL_LEDGER_CONFLICT') end
end
local exhausted=d.posts<d.threshold and count>=tonumber(ARGV[12]) and not annual_ok
if exhausted and mode~='finish' then
 -- A process/network crash can leave an incremented claim counter with a
 -- running marker. It is NOT proof of a completed content attempt. Require
 -- a real verified finish before terminal budget completion on resumption.
 local previous=old and cjson.decode(old) or {}
 if previous.status~='retry_pending' or previous.verifiedContentAttempt~=true then exhausted=false end
end
if exhausted and mode~='finish' and old then
 local previous=string.upper(old)
 for _,p in ipairs({'LOGIN_REQUIRED','SECURITY_CHALLENGE','PLATFORM_RESTRICTION','LEASE_LOST','IMPORT_FAILED','MYSQL','COOLDOWN','SAFETY_HOLD'}) do
  if string.find(previous,p,1,true) then
   return cjson.encode({status='retry_exhausted_action_required',changed=false}) end
 end
end
if d.posts<d.threshold and mode=='finish' and not annual_ok and not exhausted then
 local value=cjson.encode({status='retry_pending',accepted=false,verifiedContentAttempt=true,keyword=task.keyword,
  topic=task.topic,messageId=mid,worker=consumer,volumeAcceptance=d,updatedAt=ARGV[14]})
 redis.call('HSET',history,field..'|attempt|'..count,old or '')
 redis.call('HSET',status,id,value)
 return cjson.encode({status='retry_pending',changed=false,volumeAcceptance=d}) end
-- Encode/validate all values before the first write: Lua errors do not roll back.
local archive=cjson.encode({taskId=id,messageId=mid,originalPayload=payload,
 originalStatus=old or cjson.null,originalDelivery=pending,at=now})
local value=cjson.encode({status='completed',accepted=true,businessCompleted=true,
 acceptedBy=exhausted and 'retry_exhausted_completion' or annual_ok and 'verified_low_year_search' or 'keyword_post_count_p80',
 quantityAccepted=not annual_ok and not exhausted,annualAcceptance=annual_ok and annual or cjson.null,
 retryExhaustedCompletion=exhausted,attempts=count,retryBudget=tonumber(ARGV[12]),missingPosts=math.max(0,d.threshold-d.posts),
 qualityVerified=false,subtitleRetriesRequired=false,volumeAcceptance=d,topic=task.topic,
 keyword=task.keyword,messageId=mid,updatedAt=ARGV[14],worker=consumer})
if d.posts>=d.threshold or annual_ok or exhausted then
 if not redis.call('HGET',history,field) then redis.call('HSET',history,field,archive) end
 redis.call('HSET',history,field..'|completion',archive)
 if annual_ok then redis.call('HSET',history,annual_field,cjson.encode({generation=generation,completedResult=value,archive=archive,at=now})) end
 if exhausted then redis.call('HSET',history,exhausted_field,cjson.encode({generation=generation,snapshotId=d.snapshotId,completedResult=value,archive=archive,at=now})) end
 redis.call('HSET',status,id,value);redis.call('XACK',stream,group,mid)
 redis.call('HDEL',tokens,id)
 return cjson.encode({status='completed',acceptedByVolume=not annual_ok and not exhausted,acceptedByExhaustion=exhausted,acceptedByAnnual=annual_ok,changed=true,volumeAcceptance=d,annualAcceptance=annual})
end
-- FORCE reuses the retained exact message even if a previous scan ACKed it.
-- It neither XADDs a keyword nor resets the shared group's stream position.
local claimed=redis.call('XCLAIM',stream,group,consumer,mode=='delivered' and 0 or idle,mid,'FORCE')
if #claimed~=1 then return cjson.encode({status='busy',changed=false}) end
if not redis.call('HGET',history,field) then redis.call('HSET',history,field,archive) end
redis.call('HSET',tokens,id,token);redis.call('HINCRBY',tries,field,1)
redis.call('HSET',status,id,cjson.encode({status='running',keyword=task.keyword,topic=task.topic,
 worker=consumer,messageId=mid,volumeAcceptance=d,updatedAt=ARGV[14]}))
return cjson.encode({status='claimed',changed=true,attempt=count+1})
"""


class VolumeRuntime:
    def __init__(self, api, args, tasks, config):
        self.api, self.args, self.tasks, self.config = api, args, tasks, config
        self.manifest = []
        for item in tasks:
            topic = (item.get('queue') or {}).get('tasks', [{}])[0]
            project = {'topic1':'全国地产设计产品力监测', 'topic2':'北京臻澐项目口碑'}.get(item['topic'], topic.get('project'))
            if not project:
                raise RuntimeError('VOLUME_PROJECT_MISSING')
            self.manifest.append({'taskId':item['task_id'], 'keyword':item['keyword'], 'projectName':project})
        key = args.prefix+':volume-policy-snapshots'
        existing = self.command('HGET',key,config['generation'])
        snapshot = json.loads(existing) if existing else bridge(args.common, {'operation':'snapshot','tasks':self.manifest})
        if not existing:
            if not snapshot.get('threshold'):
                raise RuntimeError('VOLUME_POPULATION_EMPTY')
            raw = self.command('EVAL', 'local old=redis.call("HGET",KEYS[1],ARGV[1]);if old then return old end;redis.call("HSET",KEYS[1],ARGV[1],ARGV[2]);return ARGV[2]', 1,
                key, config['generation'], json.dumps(snapshot,ensure_ascii=False))
            snapshot = json.loads(raw)
        bridge(args.common, {'operation':'validate','snapshot':snapshot,'tasks':self.manifest})
        if snapshot.get('population')!='nonzero_keywords' or snapshot.get('threshold',0)<1:
            raise RuntimeError('VOLUME_SHARED_SNAPSHOT_MISMATCH')
        self.snapshot = snapshot
        state = args.worker_root/'.state'
        state.mkdir(parents=True,exist_ok=True)
        self.snapshot_file = state/'volume-acceptance-snapshot.json'
        self.snapshot_file.write_text(json.dumps(snapshot,ensure_ascii=False,indent=2),encoding='utf-8')
        self.tokens = {}
        self.cursor = 0
        self.pending_pass = False
        self.messages = {}
        for entry in self.command('XRANGE',args.stream,'-','+') or []:
            mid, item = api.decode_message(entry)
            if item['task_id'] in self.messages:
                raise RuntimeError('VOLUME_DUPLICATE_ORIGINAL_MESSAGE')
            self.messages[item['task_id']] = (mid,item)
        for task in tasks:
            existing = self.messages.get(task['task_id'])
            if not existing or existing[1]!=task:
                raise RuntimeError('VOLUME_ORIGINAL_MANIFEST_MISMATCH')
        selected = getattr(args,'only_task_id',None)
        if selected and selected not in self.messages:
            raise RuntimeError('VOLUME_SELECTED_TASK_MISSING')
        self.selected = [t for t in tasks if not selected or t['task_id']==selected]
        self.recollection=ResetOncePolicy(self.command,args)

    def command(self,*parts):
        return self.api.redis_command(self.args.redis_url,self.args.redis_password,*parts)

    def read(self,task_id):
        return bridge(self.args.common,{'operation':'task','snapshot':self.snapshot,'taskId':task_id})

    def annual_closed(self,task_id):
        raw=self.command('HGET',self.args.status_key,task_id)
        ledger=self.command('HGET',self.args.prefix+':volume-policy-history',
            task_id+'|'+self.config['generation']+'|annual-search-completion')
        try:
            result=json.loads(raw) if raw else {}
            archive=json.loads(ledger) if ledger else {}
            evidence=result.get('annualAcceptance') or {}
            return bool(archive.get('completedResult')==raw
                and archive.get('generation')==self.config['generation']
                and result.get('status')=='completed' and result.get('accepted') is True
                and result.get('quantityAccepted') is False
                and result.get('acceptedBy')=='verified_low_year_search'
                and evidence.get('taskId')==task_id
                and evidence.get('policy')=='20261016-keyword-p80-or-low-year-v2'
                and evidence.get('snapshotId')==self.snapshot['snapshotId'])
        except (ValueError,TypeError,AttributeError):
            return False

    def apply(self,item,mid,decision,*,finish=False,delivered=False,annual=None):
        parent = str(item.get('source_task_id') or item['task_id'])
        if (decision.get('snapshotId')!=self.snapshot['snapshotId']
                or decision.get('threshold')!=self.snapshot['threshold']
                or decision.get('taskId')!=parent):
            raise RuntimeError('VOLUME_SNAPSHOT_MISMATCH')
        task = next(t for t in self.tasks if t['task_id']==parent)
        identity = next(t for t in self.manifest if t['taskId']==parent)
        token = self.tokens.get(parent) if finish else secrets.token_hex(24)
        stamp = int(datetime.fromisoformat(decision['checkedAt'].replace('Z','+00:00')).timestamp()*1000)
        a = self.args
        result = json.loads(self.command('EVAL',TRANSITION,5,a.stream,a.status_key,
            a.prefix+':volume-policy-history',a.prefix+':volume-lease-tokens',a.prefix+':volume-attempts',
            parent,mid,a.group,a.consumer,self.config['generation'],token or '', 'finish' if finish else 'delivered' if delivered else 'prepare',
            json.dumps(decision,ensure_ascii=False),json.dumps(task,ensure_ascii=False),
            a.reclaim_idle_seconds*1000,stamp,3,identity['projectName'],datetime.now().astimezone().isoformat(),
            json.dumps(annual,ensure_ascii=False)))
        if result['status']=='claimed':
            self.tokens[parent]=token
        return result

    def claim_next(self, stop):
        while self.cursor<len(self.selected):
            if stop():
                return None
            task = self.selected[self.cursor]
            self.cursor+=1
            mid,_ = self.messages[task['task_id']]
            replay=self.recollection.prepare(task['task_id'],mid)
            if replay['status']!='absent':
                if replay['status']=='claimed':
                    self.tokens[task['task_id']]=replay['token']
                    return mid,{**task,'_recollectPolicy':RECOLLECT_POLICY}
                if replay['status']=='busy':self.pending_pass=True
                continue
            decision = self.read(task['task_id'])
            result = self.apply(task,mid,decision)
            if result['status']=='unread_requires_sequential_delivery' and not getattr(self.args,'only_task_id',None):
                official = self.api.read_new(self.args.redis_url,self.args.redis_password,
                    self.args.stream,self.args.group,self.args.consumer,1)
                if not official:
                    continue
                mid,task = official
                original = self.messages.get(task['task_id'])
                if not original or original!=(mid,task):
                    raise RuntimeError('VOLUME_OFFICIAL_DELIVERY_MISMATCH')
                decision = self.read(task['task_id'])
                result = self.apply(task,mid,decision,delivered=True)
            print(json.dumps({'event':'volume_keyword_decision','taskId':task['task_id'],
                'keyword':task['keyword'],'posts':decision['posts'],'threshold':decision['threshold'],
                'status':result['status']},ensure_ascii=False),flush=True)
            if result['status']=='claimed':
                return mid,dict(task)
            if result['status'] in ('busy','unread_requires_sequential_delivery'):
                self.pending_pass=True
        return None

    def finish(self,item,mid,*,child_exit_code=0):
        if child_exit_code!=0 and (child_exit_code!=4 or not content_attempt_verified(self.args,item,child_exit_code)):
            raise RuntimeError('VOLUME_CHILD_FAILURE_NOT_CONTENT_COMPLETION')
        decision=self.read(item['task_id'])
        annual=None
        if not decision.get('ok') and child_exit_code==0:
            proof=self.api.primary_search_evidence_readback(item)
            if proof.get('ok') is True:
                envelope=proof['envelope']
                state_key=self.args.prefix+':video-state:'+self.api.safe_token(item['task_id'])
                raw=self.command('HGETALL',state_key) or []
                values=self.api.fields_to_dict(raw)
                checkpoints={}
                for fp,value in values.items():
                    try:
                        checkpoints[fp]=json.loads(value)
                    except (ValueError,TypeError):
                        checkpoints[fp]={'status':'invalid_json'}
                scan={'taskId':decision['taskId'],'keyword':decision['keyword'],
                    'projectName':decision['projectName'],'year':2026,'ok':True,
                    'policy':'20261015-bound-search-end-v1','startedAtTop':True,'latestConfirmed':False,
                    'orderIndependentExhaustiveScan':True,
                    'scope':'platform_current_visible_results','observations':proof['observations'],
                    'startedAt':envelope['startedAt'],'finishedAt':envelope['finishedAt'],
                    'rawEvidenceDigest':proof['evidenceDigest']}
                assessed=bridge(self.args.common,{'operation':'annual','snapshot':self.snapshot,
                    'taskId':item['task_id'],'scan':scan,'checkpoints':checkpoints,'year':2026})
                decision=assessed['decision']
                annual=assessed['evidence']
        result=self.apply(item,mid,decision,finish=True,annual=annual)
        if annual is not None:
            result['annualAcceptance']=annual
        return result


def read_volume_config(common):
    """Read/validate local policy without Redis, SQL, or filesystem writes."""
    file = common/'acceptance-policy.json'
    if not file.is_file():
        return None
    config = json.loads(file.read_text(encoding='utf-8-sig'))
    if config.get('enabled') is not True:
        return None
    if (config.get('policy')!=POLICY or config.get('population')!='nonzero_keywords'
            or not re.fullmatch(r'[-_a-zA-Z0-9]{1,100}',config.get('generation',''))):
        raise RuntimeError('VOLUME_CONFIG_INVALID')
    return config


def content_attempt_verified(args,item,code):
    if code==0:
        return True
    if code!=4:
        return False
    try:
        report=json.loads((args.worker_root/'.state/worker_status.json').read_text(encoding='utf-8-sig'))
        expected=item['_localSearchScan']['expected']
        keywords=[k for t in report['tasks'] for k in t['keywords']]
        return bool(report.get('runToken')==expected['runToken'] and expected['runToken']
            and report.get('redisTaskId')==item['task_id'] and len(keywords)==1
            and keywords[0].get('keyword')==item['keyword']
            and keywords[0].get('status')=='partial'
            and keywords[0].get('mysql',{}).get('status')=='success')
    except (OSError,ValueError,TypeError,KeyError,AttributeError):
        return False


def recollection_outcome(args,item,code):
    record={'exitCode':code,'importOk':False,'collectionSucceeded':False,'error':'CHILD_EXIT_'+str(code),
            'localEvidenceFile':str(args.worker_root/'.state/worker_status.json')}
    try:
        report=json.loads((args.worker_root/'.state/worker_status.json').read_text(encoding='utf-8-sig'))
        expected=item['_localSearchScan']['expected']
        if (report.get('runToken')!=expected['runToken'] or not expected['runToken']
                or report.get('redisTaskId')!=item['task_id']):return record
        keywords=[k for t in report['tasks'] for k in t['keywords']]
        if len(keywords)!=1 or keywords[0].get('keyword')!=item['keyword']:return record
        row=keywords[0]
        record.update(importOk=row.get('mysql',{}).get('status')=='success',
            collectionSucceeded=code==0 and row.get('status')=='completed',status=row.get('status'),
            error=row.get('error') or (None if code==0 else record['error']))
    except (OSError,ValueError,TypeError,KeyError,AttributeError):pass
    return record


def open_runtime(api,args,tasks):
    config = read_volume_config(args.common)
    if config is None:
        if getattr(args, 'only_task_id', None):
            raise RuntimeError('SELECTED_ORIGINAL_REQUIRES_VOLUME_POLICY')
        return None
    return VolumeRuntime(api,args,tasks,config)


def preflight_local_environment(args):
    """Reject local runtime failures before consuming an original task attempt."""
    env=os.environ.copy()
    env['SOCIAL_VOLUME_ENABLED']='1'
    env['WECHAT_WORKER_ROOT']=str(args.worker_root)
    env['WECHAT_PYTHON']=sys.executable
    node=args.common/'runtime/node/node.exe'
    if node.is_file():
        env['WECHAT_NODE']=str(node)
    check=subprocess.run(['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass',
        '-File',str(args.common/'check-env.ps1')],capture_output=True,text=True,
        encoding='utf-8',errors='replace',timeout=90,env=env,
        creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    try:
        report=json.loads(check.stdout.lstrip('\ufeff'))
    except (ValueError,TypeError):
        raise RuntimeError('VOLUME_LOCAL_PREFLIGHT_UNCONFIRMED') from None
    if check.returncode or report.get('ok') is not True:
        failed=[str(c.get('name','unknown')) for c in report.get('checks',[])
            if c.get('required',True) and not c.get('ok')]
        raise RuntimeError('VOLUME_LOCAL_PREFLIGHT_FAILED:'+','.join(failed))
    return report


def run_volume_worker(api,args,stop_requested,control):
    """Bounded content attempts over originals; no subtitle retry starvation.

    An active original delivery is untouched. After three attempts in this
    policy generation an under-target keyword closes by the user's finite
    retry policy; actual SQL counts and the remaining deficit stay visible.
    """
    runtime = args.volume_runtime
    preflight_local_environment(args)
    stop_file = args.worker_root/'.state'/'stop.requested'
    state_file = args.worker_root/'.state'/'redis_worker_status.json'
    service = api.PersistentAsrService(args)
    operations=OperationalGate(runtime.command,args.worker_root.name,keys=(args.prefix+':monitor:incidents',args.prefix+':monitor:outbox'))
    attempts = completed = 0
    def stopped():
        return stop_requested.is_set() or stop_file.exists() or control.poll()
    def request_stop(signum, frame):
        stop_requested.set()
        stop_file.write_text(datetime.now().astimezone().isoformat(),encoding='utf-8')
    signal.signal(signal.SIGINT,request_stop)
    signal.signal(signal.SIGTERM,request_stop)
    try:
        while not stopped():
            if not operations.wait(stopped):
                break
            message = runtime.claim_next(stopped)
            if not message:
                if getattr(runtime,'pending_pass',False) and not args.once and not getattr(args,'only_task_id',None):
                    # Full workers revisit existing content retries after a
                    # quiet, interruptible interval. Exact/--once tests retain
                    # their one-attempt scope; no new keyword is published.
                    api.write_json(state_file,{'status':'volume_retry_wait','attempts':attempts,
                        'completedThisPass':completed,'updatedAt':datetime.now().astimezone().isoformat()})
                    end=time.monotonic()+60
                    while time.monotonic()<end and not stopped():
                        time.sleep(0.5)
                    runtime.cursor=0
                    runtime.pending_pass=False
                    continue
                break
            mid,item = message
            before_incident=operations.read().get('lastSeenAt',0)
            try:
                code = api.run_task(args,mid,item,state_file,lease_stream=args.stream,
                    lease_group=args.group,task_kind='primary',asr_service=service)
            except Exception:
                if not item.get('_recollectPolicy'):raise
                code=-1
            if code == 75:
                # Do not classify network/lease failure as content exhaustion
                # or invoke reset-once completion. Keep the delivery pending.
                api.write_json(state_file, {'status':'infrastructure_paused',
                    'taskId':item['task_id'],'messageId':mid,'childExitCode':75,
                    'localCheckpointRetained':True,'remoteSyncConfirmed':False,
                    'updatedAt':datetime.now().astimezone().isoformat()})
                print(json.dumps({'event':'volume_infrastructure_paused_no_ack',
                    'taskId':item['task_id'],'exitCode':75}),flush=True)
                return 75
            attempts+=1
            if item.get('_recollectPolicy'):
                outcome=recollection_outcome(args,item,code)
                incident=operations.read()
                if stopped():outcome.update(stopped=True,status='STOP_REQUESTED')
                elif incident.get('lastSeenAt',0)>before_incident:
                    outcome['status']='LOGIN_REQUIRED' if incident.get('requiresHuman') else 'COOLDOWN'
                result=runtime.recollection.finish(item['task_id'],mid,runtime.tokens[item['task_id']],outcome)
                completed+=int(result.get('acceptedByResetOnce') is True)
                api.write_json(state_file,{**result,'taskId':item['task_id'],'updatedAt':datetime.now().astimezone().isoformat()})
                print(json.dumps({'event':'reset_once_recollection_finished','taskId':item['task_id'],**result},ensure_ascii=False),flush=True)
                if stopped():break
                if result.get('status')=='paused':runtime.cursor=max(0,runtime.cursor-1)
                if args.once:return 0 if result.get('acceptedByResetOnce') else 4
                continue
            if stopped():
                break  # safe stop is never a completion confirmation
            incident=operations.read()
            if not content_attempt_verified(args,item,code) or incident.get('lastSeenAt',0)>before_incident:
                # Child has ended; release only this fenced delivery and do not
                # bill login/security/infrastructure waiting as a content try.
                paused=runtime.command('EVAL',"""
local id,field,token=ARGV[1],ARGV[2],ARGV[3]
if redis.call('HGET',KEYS[4],id)~=token then return redis.error_reply('VOLUME_LEASE_LOST') end
local pending=redis.call('XPENDING',KEYS[1],ARGV[4],ARGV[6],ARGV[6],1)
if #pending~=1 or pending[1][2]~=ARGV[5] then return redis.error_reply('VOLUME_LEASE_LOST') end
local old=redis.call('HGET',KEYS[2],id)
local t=redis.call('TIME')
local n=tonumber(redis.call('HGET',KEYS[5],field)) or 0
redis.call('HSET',KEYS[3],field..'|paused|'..t[1]..'-'..t[2],cjson.encode({statusBefore=old or cjson.null,consumedCounterBefore=n,reason=ARGV[7],contentAttemptCharged=false}))
redis.call('HSET',KEYS[5],field,math.max(0,n-1))
redis.call('HSET',KEYS[2],id,cjson.encode({status='safety_hold',accepted=false,reason=ARGV[7]}))
redis.call('HDEL',KEYS[4],id)
redis.call('XCLAIM',KEYS[1],ARGV[4],ARGV[5],0,ARGV[6],'IDLE',ARGV[8],'JUSTID')
return 1
""",5,args.stream,args.status_key,args.prefix+':volume-policy-history',
                    args.prefix+':volume-lease-tokens',args.prefix+':volume-attempts',item['task_id'],
                    item['task_id']+'|'+runtime.config['generation'],runtime.tokens[item['task_id']],
                    args.group,args.consumer,mid,'OPERATIONAL_HOLD' if incident.get('lastSeenAt',0)>before_incident else 'CHILD_OR_IMPORT_FAILURE',args.reclaim_idle_seconds*1000)
                if incident.get('lastSeenAt',0)>before_incident:
                    runtime.cursor=max(0,runtime.cursor-1)
                    continue
                raise RuntimeError('VOLUME_CHILD_FAILURE_PAUSED_NOT_COMPLETED')
            if incident.get('status')=='cooling':
                operations.resolve()
            result = runtime.finish(item,mid,child_exit_code=code)
            if result.get('status')=='retry_pending':
                runtime.pending_pass=True
            keyword_complete=any(result.get(k) is True for k in ('acceptedByVolume','acceptedByAnnual','acceptedByExhaustion'))
            completed+=int(keyword_complete)
            api.write_json(state_file,{'status':result['status'],'taskId':item['task_id'],
                'childExitCode':code,'volumeAcceptance':result.get('volumeAcceptance'),
                'quantityOnly':result.get('acceptedByVolume') is True,'annualAcceptance':result.get('annualAcceptance'),'qualityVerified':False,
                'updatedAt':datetime.now().astimezone().isoformat()})
            print(json.dumps({'event':'volume_keyword_attempt_finished','taskId':item['task_id'],
                'childExitCode':code,**result},ensure_ascii=False),flush=True)
            if args.once:
                return 0 if keyword_complete else 4
        # Do not equate a completed scheduling pass with all keywords accepted.
        api.write_json(state_file,{'status':'volume_pass_finished' if not stopped() else 'stopped',
            'attempts':attempts,'completedThisPass':completed,'allKeywordsComplete':False,
            'quantityOnly':True,'qualityVerified':False,
            'updatedAt':datetime.now().astimezone().isoformat()})
        return 130 if stopped() else 0
    finally:
        service.stop()
