// Shared by the read-only status check and the atomic task-claim guard. Keys
// are explicit and stay in the campaign's Redis Cluster slot. No migration or
// deletion of legacy shared state is performed here.
export const COOLDOWN_SCOPE_VERSION='xhs-node-isolation-20261021-v1';
export const COOLDOWN_SCOPE_LUA=`
local function cooldown_scope(raw, incidents_key, field, now, shared_key)
 local s=raw and cjson.decode(raw) or {count=0,untilMs=0,manualRequired=false}
 if type(s)~='table' then error('COOLDOWN_STATE_INVALID') end
 if s.manualRequired~=nil and type(s.manualRequired)~='boolean' then error('COOLDOWN_STATE_INVALID') end
 if s.untilMs~=nil and not tonumber(s.untilMs) then error('COOLDOWN_STATE_INVALID') end
 local own_raw=incidents_key and field~='' and redis.call('HGET',incidents_key,field) or false
 local own=own_raw and cjson.decode(own_raw) or nil
 if own and type(own)~='table' then error('NODE_INCIDENT_INVALID') end
 if own and own.status~='ready' and own.status~='resolved' and own.status~='manual_required' and own.status~='cooling' then
  error('NODE_INCIDENT_INVALID')
 end
 if own and own.status~='ready' and own.status~='resolved' and own.kind~='login' and own.kind~='captcha' and own.kind~='security' then
  error('NODE_INCIDENT_INVALID')
 end
 if own and own.status=='cooling' and not tonumber(own.cooldownUntil) then error('NODE_INCIDENT_INVALID') end
 local legacy_scoped=false
 -- Old writers stored only workerId in the shared hold. Attribute it only
 -- when a matching login/captcha incident spans the Redis event timestamp.
 -- Unknown or explicitly group-scoped holds remain fail-closed.
 if s.manualRequired and s.scope~='group' and s.reason=='manual_restriction'
  and s.restrictionKind=='manual' and type(s.workerId)=='string' and s.workerId~=''
  and tonumber(s.lastIncidentAt) and incidents_key then
  for _,value in ipairs(redis.call('HVALS',incidents_key)) do
   local ok,i=pcall(cjson.decode,value)
   if ok and type(i)=='table' and i.platform=='小红书' and i.workerId==s.workerId
    and (i.kind=='login' or i.kind=='captcha') and tonumber(i.startedAt) then
    local last=math.max(tonumber(i.lastSeenAt) or 0,tonumber(i.resolvedAt) or 0)
    if tonumber(i.startedAt)<=tonumber(s.lastIncidentAt)+10000 and last>=tonumber(s.lastIncidentAt)-10000 then
     legacy_scoped=true;break
    end
   end
  end
 end
 local shared_manual=s.manualRequired==true and not legacy_scoped
 local node_active=own and own.status~='ready' and own.status~='resolved'
 local node_manual=node_active and (own.requiresHuman==true or own.kind=='login' or own.kind=='captcha') or false
 local until_ms=tonumber(s.untilMs) or 0
 local timed_raw=shared_key and redis.call('HGET',shared_key,'timedState') or false
 if timed_raw then
  local timed=cjson.decode(timed_raw)
  if type(timed)~='table' or timed.manualRequired~=false or not tonumber(timed.untilMs) then error('TIMED_COOLDOWN_INVALID') end
  until_ms=math.max(until_ms,tonumber(timed.untilMs))
  s.count=math.max(tonumber(s.count) or 0,tonumber(timed.count) or 0)
 end
 if node_active and not node_manual then until_ms=math.max(until_ms,tonumber(own.cooldownUntil) or 0) end
 s.scopeVersion='${COOLDOWN_SCOPE_VERSION}'
 s.legacyManualScoped=legacy_scoped
 s.sharedManualRequired=shared_manual
 s.nodeManualRequired=node_manual
 s.manualRequired=shared_manual or node_manual
 s.active=s.manualRequired or until_ms>now
 s.scope=shared_manual and 'group' or node_manual and 'node' or until_ms>now and 'cooldown' or 'ready'
 s.nodeIncidentId=node_active and own.incidentId or cjson.null
 s.nodeKind=node_active and own.kind or cjson.null
 s.nodeWorkerId=own and own.workerId or cjson.null
 s.nodeMachine=own and own.machine or cjson.null
 s.serverTime=now;s.untilMs=until_ms;s.remainingMs=math.max(0,until_ms-now)
 return s
end
`;
