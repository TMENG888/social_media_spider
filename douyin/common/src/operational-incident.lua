-- Monitoring-only keys; never touch task/lease/business keys.
local states,outbox=KEYS[1],KEYS[2]
redis.call('HGET',states,'__probe__');redis.call('HGET',outbox,'__probe__')
local action,field=ARGV[1],ARGV[2]
local t=redis.call('TIME');local now=tonumber(t[1])*1000+math.floor(tonumber(t[2])/1000)
local raw=redis.call('HGET',states,field)
local old=raw and cjson.decode(raw) or nil
local function result(s) s.serverTime=now;return cjson.encode(s) end
if action=='read' then return result(old or {status='ready',requiresHuman=false}) end
if action=='resolve' then
 if not old or old.status=='resolved' then return result(old or {status='ready'}) end
 old.status='resolved';old.resolvedAt=now;old.requiresHuman=false;old.resolution=ARGV[3]
 local encoded=cjson.encode(old)
 redis.call('HSET',states,field,encoded)
 if old.notifyHuman==true then redis.call('HSET',outbox,old.incidentId..'|resolved',encoded) end
 return result(old)
end
if action~='record' then return redis.error_reply('MONITOR_ACTION_INVALID') end
local input=cjson.decode(ARGV[3])
if input.field~=field or (input.kind~='login' and input.kind~='captcha' and input.kind~='security') then
 return redis.error_reply('MONITOR_INCIDENT_INVALID') end
if old and old.status~='resolved' and old.kind==input.kind and (old.requiresHuman or (old.cooldownUntil or 0)>now) then
 old.lastSeenAt=now;redis.call('HSET',states,field,cjson.encode(old));return result(old)
end
input.status=input.requiresHuman and 'manual_required' or 'cooling'
input.notifyHuman=input.requiresHuman;input.startedAt=now;input.lastSeenAt=now
input.cooldownUntil=now+tonumber(ARGV[4]);input.incidentId=field..'-'..now..'-'..redis.call('HINCRBY',states,'__sequence__',1)
local encoded=cjson.encode(input)
redis.call('HSET',states,field,encoded)
if input.notifyHuman then redis.call('HSET',outbox,input.incidentId..'|active',encoded) end
return result(input)
