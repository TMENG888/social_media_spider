-- Technical telemetry only. No task/lease/history/business keys.
local states,outbox=KEYS[1],KEYS[2]
local action,field=ARGV[1],ARGV[2]
local d=cjson.decode(ARGV[3])
if d.kind~='database' or type(d.signature)~='string' then return redis.error_reply('DATABASE_MONITOR_INVALID') end
local raw=redis.call('HGET',states,field)
local old=raw and cjson.decode(raw) or nil
local t=redis.call('TIME');local now=tonumber(t[1])*1000+math.floor(tonumber(t[2])/1000)
if action=='resolve' then
 if d.databaseReadbackVerified~=true then return redis.error_reply('DATABASE_RECOVERY_UNVERIFIED') end
 if not old or old.status=='resolved' then return 0 end
 old.status='resolved';old.resolvedAt=now;old.databaseReadbackVerified=true
 old.recoveryTarget=d.target;old.recoveryOperation=d.operation
 local encoded=cjson.encode(old)
 redis.call('HSET',states,field,encoded)
 redis.call('HSET',outbox,old.incidentId..'|resolved',encoded)
 return 1
end
if action~='record' or d.status~='active' or type(d.errorCode)~='string' then return redis.error_reply('DATABASE_MONITOR_INVALID') end
if old and old.status=='active' and old.signature==d.signature then
 old.lastSeenAt=now;redis.call('HSET',states,field,cjson.encode(old));return 0
end
d.startedAt=now;d.lastSeenAt=now
d.incidentId=field..'-database-'..now..'-'..redis.call('HINCRBY',states,'__sequence__',1)
local encoded=cjson.encode(d)
redis.call('HSET',states,field,encoded)
redis.call('HSET',outbox,d.incidentId..'|active',encoded)
return 1
