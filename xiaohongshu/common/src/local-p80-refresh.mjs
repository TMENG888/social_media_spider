import {randomUUID} from 'node:crypto';
export const LOCAL_P80_REFRESH_POLICY='xhs-p80-db-net3000-or24h-20261107-v1';
export const REFRESH_INCREMENT=3000;
export const REFRESH_MAX_AGE_MS=24*60*60*1000;
export const REFRESH_POLL_MS=5*60*1000;
const KEY_PROBE=`for _,key in ipairs(KEYS) do redis.call('HGET',key,'__p80_refresh_probe__') end\n`;
const NOW=`local t=redis.call('TIME');local now=tonumber(t[1])*1000+math.floor(tonumber(t[2])/1000)\n`;
export async function refreshLocalP80({client,namespace,readDatabaseCount,pollMs=REFRESH_POLL_MS}){
 if(!/^xhs:\{[A-Za-z0-9_-]{1,200}\}$/.test(namespace))throw new Error('P80_REFRESH_NAMESPACE_INVALID');
 if(!Number.isSafeInteger(pollMs)||pollMs<0)throw new Error('P80_REFRESH_POLL_INVALID');
 const keys=[namespace+':local-p80-meta',namespace+':local-p80-counts',namespace+':local-p80-refresh'];
 const token=randomUUID();
 const acquired=await client.eval(KEY_PROBE+NOW+`
if not redis.call('HGET',KEYS[1],'ready') then return 'not_ready' end
local next=tonumber(redis.call('HGET',KEYS[3],'nextPollAtMs')) or 0
local until_ms=tonumber(redis.call('HGET',KEYS[3],'leaseUntilMs')) or 0
if until_ms>now or next>now then return 'busy_or_not_due' end
redis.call('HSET',KEYS[3],'owner',ARGV[1],'leaseUntilMs',now+45000,'nextPollAtMs',now+tonumber(ARGV[2]));return 'acquired'`,{keys,arguments:[token,String(pollMs)]});
 if(acquired!=='acquired')return {refreshed:false,reason:acquired};
 try{
  const observed=await readDatabaseCount();
  if(!Number.isSafeInteger(observed)||observed<0)throw new Error('P80_DATABASE_COUNT_INVALID');
  return JSON.parse(await client.eval(KEY_PROBE+NOW+`
if redis.call('HGET',KEYS[3],'owner')~=ARGV[1] or (tonumber(redis.call('HGET',KEYS[3],'leaseUntilMs')) or 0)<=now then return cjson.encode({refreshed=false,reason='lease_lost'}) end
local observed=tonumber(ARGV[2]);local baseline=tonumber(redis.call('HGET',KEYS[1],'databaseBaseline'))
local last=tonumber(redis.call('HGET',KEYS[1],'thresholdRefreshedAtMs'))
local cached=tonumber(redis.call('HGET',KEYS[1],'frozenThreshold'))
local active=redis.call('HGET',KEYS[1],'refreshPolicy')=='${LOCAL_P80_REFRESH_POLICY}'
local reason=nil
if not active or not cached then reason='initial'
elseif not baseline or not last then return redis.error_reply('P80_REFRESH_BASELINE_INVALID')
elseif observed-baseline>=${REFRESH_INCREMENT} then reason='database_net_3000'
elseif now-last>=${REFRESH_MAX_AGE_MS} then reason='max_age_24h' end
local threshold,samples=cached,tonumber(redis.call('HGET',KEYS[1],'frozenSamples'))
if reason then
 local values=redis.call('HVALS',KEYS[2]);local counts={}
 for _,raw in ipairs(values) do local n=tonumber(raw);if not n or n<0 then return redis.error_reply('P80_LOCAL_COUNT_INVALID') end;if n>0 then table.insert(counts,n) end end
 if #counts==0 then return redis.error_reply('P80_LOCAL_POPULATION_EMPTY') end
 table.sort(counts);threshold=counts[math.ceil(#counts*4/5)];samples=#counts
end
-- Validate the entire proposed snapshot before updating the shared baseline.
redis.call('HSET',KEYS[3],'observedDatabasePosts',observed,'observedAtMs',now,'leaseUntilMs',0,'lastErrorCode','')
redis.call('HDEL',KEYS[3],'owner')
if reason then
 local version=(tonumber(redis.call('HGET',KEYS[1],'thresholdSnapshotVersion')) or 0)+1
 redis.call('HSET',KEYS[1],'refreshPolicy','${LOCAL_P80_REFRESH_POLICY}','refreshIncrement',${REFRESH_INCREMENT},
  'refreshMaxAgeMs',${REFRESH_MAX_AGE_MS},'frozenThreshold',threshold,'frozenSamples',samples,
  'databaseBaseline',observed,'thresholdRefreshedAtMs',now,'thresholdSnapshotVersion',version,'thresholdRefreshReason',reason)
 return cjson.encode({refreshed=true,reason=reason,threshold=threshold,samples=samples,databaseBaseline=observed,refreshedAtMs=now,version=version})
end
return cjson.encode({refreshed=false,reason='below_increment_and_age',threshold=threshold,samples=samples,
 databaseBaseline=baseline,observed=observed,netIncrease=observed-baseline,refreshedAtMs=last})`,{keys,arguments:[token,String(observed)]}));
 }catch(error){
  const code=/^[A-Z][A-Z0-9_]{0,63}$/.test(error?.code||'')?error.code:'P80_REFRESH_FAILED';
  await client.eval(KEY_PROBE+NOW+`
if redis.call('HGET',KEYS[3],'owner')==ARGV[1] then
 redis.call('HSET',KEYS[3],'leaseUntilMs',0,'nextPollAtMs',now+60000,'lastErrorCode',ARGV[2],'lastErrorAtMs',now)
 redis.call('HDEL',KEYS[3],'owner')
end;return 1`,{keys,arguments:[token,code]}).catch(()=>{});
  throw error;
 }
}
export async function readDatabaseUniquePosts({connect}){
 let connection,timer;
 const timeout=Object.assign(new Error('P80 database query timeout'),{code:'P80_DATABASE_TIMEOUT'});
 try{
  return await Promise.race([(async()=>{
   const pending=connect();connection=await pending;
   if(timer===null){connection.destroy();throw timeout;}
   const [rows]=await connection.query({sql:"SELECT COUNT(DISTINCT NULLIF(TRIM(`文章id`),'')) AS posts FROM ods_social_media_post WHERE `平台`=?",values:['小红书'],timeout:15000});
   const n=Number(rows[0]?.posts);if(!Number.isSafeInteger(n)||n<0)throw new Error('P80_DATABASE_COUNT_INVALID');return n;
  })(),new Promise((_,reject)=>{timer=setTimeout(()=>{timer=null;connection?.destroy();reject(timeout);},20000);})]);
 }finally{
  if(timer)clearTimeout(timer);connection?.destroy();
 }
}
