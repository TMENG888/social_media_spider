import fs from 'node:fs/promises';
import path from 'node:path';
import {createHash} from 'node:crypto';
import {redisSettings,connectRedis} from './redis-connection.mjs';
import {loadTaskManifest} from './redis-task-manifest.mjs';
import {writeJsonAtomic} from './checkpoint.mjs';
import {OperationalGate,classifyRestriction} from './operational-gate.mjs';
import {COOLDOWN_SCOPE_LUA} from './cooldown-scope.mjs';
import {isStorageFull,storageStopMarker} from './local-storage-stop.mjs';

export const COOLDOWN_EXIT = 76;
export const MANUAL_COOLDOWN_EXIT = 77;
export function restrictionKind(message) {
  const text=String(message?.message || message || '');
  if (/^STOP_LOGIN_REQUIRED/.test(text)) return 'manual';
  if (!/^STOP_SECURITY_CHALLENGE/.test(text)) return null;
  // Never interpret a CAPTCHA/login/network challenge as a timed rate limit.
  return classifyRestriction(text)?.requiresHuman ? 'manual' : 'rate';
}
export function cooldownWorkerExit({fatalError=null,lost=false,status={}}) {
  if(fatalError?.code==='LEASE_LOST' || lost)return 5;
  const unrelatedFailure=(status.tasks || []).some(task=>
    ['import_failed','lease_lost','confirmation_failed','context_lost'].includes(task.status) ||
    (task.importExitCode!=null && ![0,75].includes(task.importExitCode)));
  const eligible=(!fatalError || ['RATE_LIMIT_COOLDOWN_ACTIVE','COOLDOWN_MANUAL_REQUIRED'].includes(fatalError.code) ||
    (restrictionKind(fatalError)!=null && status.cooldown?.active)) && !unrelatedFailure;
  if(eligible && !status.failedCount && status.cooldown?.active)
    return status.cooldown.manualRequired ? MANUAL_COOLDOWN_EXIT : COOLDOWN_EXIT;
  return fatalError || unrelatedFailure || status.failedCount || status.globalQueue?.failed ? 1 : 0;
}
const PRELUDE = `
if redis.replicate_commands then redis.replicate_commands() end
local t=redis.call('TIME')
local now=tonumber(t[1])*1000+math.floor(tonumber(t[2])/1000)
local raw=redis.call('HGET',KEYS[1],'state')
local s=raw and cjson.decode(raw) or {count=0,untilMs=0,manualRequired=false}
local function result()
  s.serverTime=now
  s.active=s.manualRequired or (s.untilMs or 0)>now
  s.remainingMs=math.max(0,(s.untilMs or 0)-now)
  return cjson.encode(s)
end
`;
const RECORD = PRELUDE + `
if ARGV[2]~='rate' then return redis.error_reply('SHARED_COOLDOWN_RATE_ONLY') end
-- Keep timed limits independent of legacy manual state; do not overwrite its
-- source/evidence or let an old login hold suppress a new group rate limit.
local timed_raw=redis.call('HGET',KEYS[1],'timedState')
local legacy=s
s=timed_raw and cjson.decode(timed_raw) or {count=0,untilMs=0,manualRequired=false}
if type(s)~='table' or s.manualRequired~=false or not tonumber(s.untilMs) then return redis.error_reply('TIMED_COOLDOWN_INVALID') end
if not legacy.manualRequired then
 s.untilMs=math.max(s.untilMs,tonumber(legacy.untilMs) or 0)
 s.count=math.max(tonumber(s.count) or 0,tonumber(legacy.count) or 0)
end
local event='event:'..ARGV[1]
if redis.call('HEXISTS',KEYS[1],event)==1 then return result() end
redis.call('HSET',KEYS[1],event,now)
if not s.manualRequired and (s.untilMs or 0)<=now then
  s.count=(s.count or 0)+1
  -- Repeated ordinary rate limits stay timed: 2h, then capped at 4h by
  -- default. A rate counter must not invent a CAPTCHA/manual requirement.
  -- Existing explicit/legacy manual holds are never downgraded here.
  s.untilMs=now+tonumber(ARGV[3+math.min(s.count,2)])
  s.reason='rate_limit'
  s.restrictionKind='rate'
  s.automaticResume=true
else
  -- Multiple nodes observing the same cooling interval are one incident.
  return result()
end
s.workerId=ARGV[3]
s.lastIncidentAt=now
redis.call('HSET',KEYS[1],'timedState',cjson.encode(s))
-- Old-version nodes still see timed holds through 'state'. Never overwrite
-- a legacy manual hold or its attribution just to publish a timed limit.
if not legacy.manualRequired then redis.call('HSET',KEYS[1],'state',cjson.encode(s)) end
return result()
`;
const RESET = PRELUDE + `
redis.call('HSET',KEYS[1],'reset:'..ARGV[1],cjson.encode(s))
local timed_raw=redis.call('HGET',KEYS[1],'timedState')
if timed_raw then redis.call('HSET',KEYS[1],'reset:timed:'..ARGV[1],timed_raw);redis.call('HDEL',KEYS[1],'timedState') end
s={count=0,untilMs=0,manualRequired=false,resetAt=now,resetBy=ARGV[2]}
redis.call('HSET',KEYS[1],'state',cjson.encode(s))
return result()
`;
export const READ_SCOPED_COOLDOWN = COOLDOWN_SCOPE_LUA + `
local t=redis.call('TIME');local now=tonumber(t[1])*1000+math.floor(tonumber(t[2])/1000)
return cjson.encode(cooldown_scope(redis.call('HGET',KEYS[1],'state'),KEYS[2],ARGV[1],now,KEYS[1]))
`;
export class CooldownActiveError extends Error {
  constructor(state) {
    super(state.manualRequired ? 'COOLDOWN_MANUAL_REQUIRED：平台限制需人工确认，禁止自动恢复'
      : 'RATE_LIMIT_COOLDOWN_ACTIVE：共享冷却中，不访问平台、不领取新任务');
    this.code=state.manualRequired?'COOLDOWN_MANUAL_REQUIRED':'RATE_LIMIT_COOLDOWN_ACTIVE';
    this.state=state;
  }
}
export class RateLimitCooldown {
  static async open({root,stateRoot,workerId,campaign=null,onStage=()=>{}}) {
    onStage('READ_REDIS_SETTINGS');
    const settings=await redisSettings(root);
    if(!campaign){
      campaign=settings.taskPoolCampaign;
      if(!campaign){
        onStage('READ_MANIFEST');
        const manifest=await loadTaskManifest(path.join(root,'tasks','redis-tasks.json'));
        campaign=`${settings.campaign}-mysql-${manifest.manifestHash.slice(0,16)}`;
      }
    }
    onStage('READ_PLATFORM_CONFIG');
    const config=JSON.parse((await fs.readFile(path.join(root,'config.json'),'utf8')).replace(/^\uFEFF/,''));
    const policy=config.rateLimitCooldown || {};
    onStage('CONNECT_REDIS');
    const client=await connectRedis(settings);
    try { return new RateLimitCooldown({client,campaign,stateRoot,workerId,group:policy.group || 'shared',
      delaysMs:policy.delaysMs || [7200000,14400000]}); }
    catch(error){await client.close();throw error;}
  }
  constructor({client,campaign,stateRoot,workerId,group='shared',delaysMs=[7200000,14400000]}) {
    if(!/^[A-Za-z0-9_-]{1,160}$/.test(campaign) || !/^[A-Za-z0-9_-]{1,64}$/.test(group))
      throw new Error('Invalid cooldown campaign/group');
    if(delaysMs.length!==2 || !delaysMs.every(n=>Number.isSafeInteger(n)&&n>0))
      throw new Error('Cooldown needs two positive delays');
    Object.assign(this,{client,campaign,stateRoot,workerId,group,delaysMs});
    this.key=`xhs:{${campaign}}:rate-limit-cooldown:${group}`;
    this.writes=Promise.resolve();
    this.operations=new OperationalGate({client,workerId,platform:'小红书',keys:[`xhs:{${campaign}}:monitor:incidents`,`xhs:{${campaign}}:monitor:outbox`]});
    this.last=null;
  }
  async evaluate(script,args=[]) {
    let state;
    try {
      state=JSON.parse(await this.client.eval(script,{keys:[this.key,this.operations.keys[0]],arguments:args.map(String)}));
      if(!Number.isFinite(state.serverTime)||typeof state.active!=='boolean')throw new Error('Invalid cooldown response');
    } catch(cause){throw Object.assign(new Error('COOLDOWN_STATE_UNAVAILABLE：无法确认共享冷却状态，停止自动访问',{cause}),{code:'COOLDOWN_STATE_UNAVAILABLE'});}
    this.last={...state,campaign:this.campaign,group:this.group};
    const snapshot=this.last;
    if(this.stateRoot){
      const write=this.writes.catch(()=>{}).then(()=>writeJsonAtomic(path.join(this.stateRoot,'rate-limit-cooldown.json'),snapshot));
      this.writes=write;
      await write;
    }
    return snapshot;
  }
  read(){return this.evaluate(READ_SCOPED_COOLDOWN,[this.operations.field]);}
  bindQueue(queue){
    // Author pools have another cluster tag and use assertReady directly.
    if(queue.namespace!==`xhs:{${this.campaign}}`)return false;
    queue.cooldownKey=this.key;
    queue.cooldownIncidentKey=this.operations.keys[0];
    queue.cooldownNodeField=this.operations.field;
    return true;
  }
  async assertReady(){const s=await this.read();if(s.active)throw new CooldownActiveError(s);return s;}
  async record(message,eventId){
    const kind=restrictionKind(message);
    if(!kind)return Promise.resolve(null);
    if(!eventId)throw new Error('Cooldown incident needs a stable event ID');
    // A login/captcha belongs to this platform+machine+worker, never the group.
    // OperationalGate retains immediate Feishu outbox notification and dedup.
    if(kind==='manual'){
      await this.operations.record(message,{cooldownMs:this.delaysMs[0]});
      return this.read();
    }
    const id=createHash('sha256').update(String(eventId)).digest('hex');
    const state=await this.evaluate(RECORD,[id,kind,this.workerId,...this.delaysMs]);
    await this.operations.record(message,{cooldownMs:kind==='rate'?Math.max(1,state.untilMs-state.serverTime):this.delaysMs[0]});
    return this.read();
  }
  async resetConfirmed(){const result=await this.evaluate(RESET,[`${Date.now()}-${process.pid}`,this.workerId]);await this.operations.resolve();return result;}
  async wait({shouldStop=async()=>false,onState=()=>{},pollMs=15000,tickMs=250,waitForManual=false}={}) {
    while(true){
      if(await shouldStop())return {stopped:true};
      const state=await this.read();
      if(await shouldStop())return {stopped:true};
      onState(state);
      if(state.manualRequired&&!waitForManual)return {manual:true,state};
      if(!state.active)return {ready:true,state};
      const end=Date.now()+(state.manualRequired?pollMs:Math.min(pollMs,state.remainingMs));
      while(Date.now()<end){
        if(await shouldStop())return {stopped:true};
        // The asynchronous stop check can cross the deadline. A negative timer
        // is coerced to 1ms by Node and emits TimeoutNegativeWarning.
        const remaining=end-Date.now();
        if(remaining<=0)break;
        await new Promise(r=>setTimeout(r,Math.max(1,Math.min(tickMs,remaining))));
      }
    }
  }
  monitor(stopFile,{intervalMs=10000,onStop=()=>{}}={}) {
    let timer,pending,closed=false;
    const check=async()=>{
      if(closed)return;
      pending=(async()=>{
        try{await this.assertReady();}
        catch(error){
          // Cooperative stop keeps current note/import intact and lease renewable.
          const marker=isStorageFull(error)?JSON.stringify(storageStopMarker({workerId:this.workerId})):
            error.code || 'COOLDOWN_STATE_UNAVAILABLE';
          await fs.writeFile(stopFile,marker,{encoding:'utf8',flag:'wx'}).catch(e=>{if(e.code!=='EEXIST')throw e;});
          onStop(error);
          closed=true;
        }
      })();
      await pending;
      if(!closed)timer=setTimeout(()=>void check(),intervalMs);
    };
    timer=setTimeout(()=>void check(),intervalMs);
    return async()=>{closed=true;clearTimeout(timer);await pending;};
  }
  async close(){await this.writes.catch(()=>{});await this.client.close();}
}
