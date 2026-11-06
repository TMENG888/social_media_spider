import {createHash} from 'node:crypto';

export const MACHINE_COOLDOWN_VERSION='xhs-machine-cooldown-20261104-v1';
export function machineCooldownGroup(group,machine){
  if(typeof machine!=='string'||!machine.trim())throw new Error('COOLDOWN_MACHINE_REQUIRED');
  return 'machine-'+createHash('sha256').update(group+'|'+machine.trim().toUpperCase()).digest('hex').slice(0,40);
}

// Only copy attributable protection into its owner's machine key. The legacy
// key and incident history stay byte-identical. Unknown active protection fails
// closed. All keys retain the campaign hash tag for Redis Cluster.
export const IMPORT_MACHINE_COOLDOWN=`
local machine=string.upper(ARGV[1])
local tm=redis.call('TIME');local now=tonumber(tm[1])*1000+math.floor(tonumber(tm[2])/1000)
local destination_raw=redis.call('HGET',KEYS[1],'timedState')
local rows=redis.call('HVALS',KEYS[3]);local incidents={}
for _,raw in ipairs(rows) do
 local ok,i=pcall(cjson.decode,raw)
 if ok and type(i)=='table' and i.platform=='小红书' then table.insert(incidents,i) end
end
local function owner(s)
 if type(s.machine)=='string' and s.machine~='' then return string.upper(s.machine) end
 local found=nil
 for _,i in ipairs(incidents) do
  local first=tonumber(i.startedAt);local last=math.max(tonumber(i.lastSeenAt) or 0,tonumber(i.resolvedAt) or 0)
  local at=tonumber(s.lastIncidentAt)
  local compatible=(s.manualRequired and (i.kind=='login' or i.kind=='captcha')) or (not s.manualRequired and i.kind=='security')
  if compatible and i.workerId==s.workerId and type(i.machine)=='string' and first and at and first<=at+10000 and last>=at-10000 then
   local candidate=string.upper(i.machine)
   if found and found~=candidate then return nil end
   found=candidate
  end
 end
 return found
end
local deadline=0;local count=0;local attribution='none'
for _,field in ipairs({'state','timedState'}) do
 local raw=redis.call('HGET',KEYS[2],field)
 if raw then
  local s=cjson.decode(raw)
  if type(s)~='table' or (s.manualRequired~=nil and type(s.manualRequired)~='boolean') or (s.untilMs~=nil and not tonumber(s.untilMs)) then return redis.error_reply('LEGACY_COOLDOWN_INVALID') end
  if s.manualRequired or (tonumber(s.untilMs) or 0)>now then
   local source=owner(s)
   if (s.manualRequired and s.scope=='group') or not source then return redis.error_reply('LEGACY_COOLDOWN_OWNER_UNCONFIRMED') end
   if source==machine then
    attribution='own_machine'
    -- Login/CAPTCHA stays in the existing node incident gate.
    if not s.manualRequired then deadline=math.max(deadline,tonumber(s.untilMs) or 0);count=math.max(count,tonumber(s.count) or 0) end
   elseif attribution=='none' then attribution='other_machine' end
  end
 end
end
-- A different worker on this same machine may have an older node timer.
local use_node_fallback=not destination_raw and deadline<=now
for _,i in ipairs(incidents) do
 if use_node_fallback and type(i.machine)=='string' and string.upper(i.machine)==machine and i.kind=='security' and i.status=='cooling' and i.requiresHuman~=true then
  local until_ms=tonumber(i.cooldownUntil)
  if not until_ms then return redis.error_reply('NODE_INCIDENT_INVALID') end
  if until_ms>now then deadline=math.max(deadline,until_ms);count=math.max(count,1) end
 end
end
local raw=destination_raw
local current=raw and cjson.decode(raw) or {count=0,untilMs=0,manualRequired=false}
if type(current)~='table' or current.manualRequired~=false or not tonumber(current.untilMs) then return redis.error_reply('TIMED_COOLDOWN_INVALID') end
-- Type-check every write destination before writing; Lua has no rollback.
local state_raw=redis.call('HGET',KEYS[1],'state')
local state=state_raw and cjson.decode(state_raw) or nil
if state and (type(state)~='table' or state.manualRequired==true) then return redis.error_reply('MACHINE_COOLDOWN_STATE_INVALID') end
local imported=false
if deadline>now and (deadline>tonumber(current.untilMs) or count>(tonumber(current.count) or 0)) then
 current.untilMs=math.max(deadline,tonumber(current.untilMs));current.count=math.max(count,tonumber(current.count) or 0)
 current.machine=ARGV[1];current.scope='machine';current.reason='rate_limit';current.restrictionKind='rate';current.automaticResume=true
 current.migratedFrom=KEYS[2];current.migratedAt=now
 local encoded=cjson.encode(current)
 redis.call('HSET',KEYS[1],'timedState',encoded,'state',encoded);imported=true
end
return cjson.encode({imported=imported,legacyAttribution=attribution,serverTime=now})
`;
