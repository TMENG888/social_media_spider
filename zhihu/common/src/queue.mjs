import {createClient} from 'redis';
import {randomUUID} from 'node:crypto';
const pre=`local function now() local t=redis.call('TIME');return tonumber(t[1])*1000+math.floor(tonumber(t[2])/1000) end
local function owns(id,t) return redis.call('HGET',KEYS[2],id)=='leased' and redis.call('HGET',KEYS[4],id)==t and tonumber(redis.call('ZSCORE',KEYS[7],id) or 0)>now() end
local function clear(id) redis.call('HDEL',KEYS[4],id);redis.call('HDEL',KEYS[5],id);redis.call('ZREM',KEYS[7],id) end
`;
export class Queue{
  constructor(client,{campaign,leaseMs=300000,maxAttempts=3,retryDelayMs=60000,prefix='xhs:zhihu'}){if(prefix!=='xhs:zhihu'||!/^[A-Za-z0-9_-]+$/.test(campaign))throw new Error('INVALID_ZHIHU_NAMESPACE');Object.assign(this,{client,leaseMs,maxAttempts,retryDelayMs});this.namespace=prefix+':{'+campaign+'}';this.keys=['payload','status','attempt','token','owner','pending','lease','result','error'].map(s=>this.namespace+':'+s);}
  async eval(script,args=[]){const r=await this.client.eval(pre+script,{keys:this.keys,arguments:args.map(String)});return r?JSON.parse(r):null;}
  async publish(tasks){return this.eval(`for i=1,#ARGV,3 do local old=redis.call('HGET',KEYS[1],ARGV[i]);if old and old~=ARGV[i+1] then return redis.error_reply('PAYLOAD_CONFLICT') end end
  local added=0;for i=1,#ARGV,3 do if redis.call('HEXISTS',KEYS[2],ARGV[i])==0 then redis.call('HSET',KEYS[1],ARGV[i],ARGV[i+1]);redis.call('HSET',KEYS[2],ARGV[i],'pending');redis.call('HSET',KEYS[3],ARGV[i],0);redis.call('ZADD',KEYS[6],ARGV[i+2],ARGV[i]);added=added+1 end end;return cjson.encode({added=added})`,tasks.flatMap(t=>[t.id,JSON.stringify(t),t.sequence]));}
  async claim(owner){return this.eval(`local n=now();for _,id in ipairs(redis.call('ZRANGEBYSCORE',KEYS[7],'-inf',n,'LIMIT',0,1000)) do clear(id);if tonumber(redis.call('HGET',KEYS[3],id) or 0)>=tonumber(ARGV[4]) then redis.call('HSET',KEYS[2],id,'failed') else redis.call('HSET',KEYS[2],id,'pending');redis.call('ZADD',KEYS[6],n,id) end;redis.call('HSET',KEYS[9],id,'LEASE_EXPIRED') end
  local ids=redis.call('ZRANGEBYSCORE',KEYS[6],'-inf',n,'LIMIT',0,1);if #ids==0 then return nil end;local id=ids[1];redis.call('ZREM',KEYS[6],id);redis.call('HSET',KEYS[2],id,'leased');redis.call('HINCRBY',KEYS[3],id,1);redis.call('HSET',KEYS[4],id,ARGV[2]);redis.call('HSET',KEYS[5],id,ARGV[1]);redis.call('ZADD',KEYS[7],n+tonumber(ARGV[3]),id);return cjson.encode({task=cjson.decode(redis.call('HGET',KEYS[1],id)),token=ARGV[2]})`,[owner,randomUUID(),this.leaseMs,this.maxAttempts]);}
  renew(id,token){return this.eval(`if not owns(ARGV[1],ARGV[2]) then return redis.error_reply('LEASE_LOST') end;redis.call('ZADD',KEYS[7],now()+tonumber(ARGV[3]),ARGV[1]);return cjson.encode({ok=true})`,[id,token,this.leaseMs]);}
  assert(id,token){return this.eval(`if not owns(ARGV[1],ARGV[2]) then return redis.error_reply('LEASE_LOST') end;return cjson.encode({ok=true})`,[id,token]);}
  finish(id,token,kind,result={}){return this.eval(`if not owns(ARGV[1],ARGV[2]) then return redis.error_reply('LEASE_LOST') end
    local r=cjson.decode(ARGV[4]);local status=ARGV[3];if status=='completed' and (r.scanComplete~=true or r.commentsComplete~=true or r.persisted~=true or r.unresolved~=0) then return redis.error_reply('INCOMPLETE_EVIDENCE') end
    if status=='released' then status='pending';redis.call('HINCRBY',KEYS[3],ARGV[1],-1);redis.call('ZADD',KEYS[6],now(),ARGV[1]) end
    if status=='retry' then if tonumber(redis.call('HGET',KEYS[3],ARGV[1]))>=tonumber(ARGV[5]) then status='failed' else status='pending';redis.call('ZADD',KEYS[6],now()+tonumber(ARGV[6]),ARGV[1]) end end
    clear(ARGV[1]);redis.call('HSET',KEYS[2],ARGV[1],status);redis.call('HSET',KEYS[8],ARGV[1],ARGV[4]);if r.error then redis.call('HSET',KEYS[9],ARGV[1],r.error) end;return cjson.encode({status=status})`,[id,token,kind,JSON.stringify(result),this.maxAttempts,this.retryDelayMs]);}
  stats(){return this.eval(`local c={pending=0,leased=0,completed=0,failed=0};for _,s in ipairs(redis.call('HVALS',KEYS[2])) do c[s]=(c[s] or 0)+1 end;return cjson.encode(c)`);}
}
export async function connect(settings){
  const u=new URL(settings.url);if(!['redis:','rediss:'].includes(u.protocol)||u.username||u.password)throw new Error('REDIS_URL_MUST_NOT_CONTAIN_PASSWORD');
  const client=createClient({url:settings.url,username:process.env.REDIS_USERNAME||settings.username||undefined,password:process.env.REDIS_PASSWORD||undefined,disableOfflineQueue:true,socket:{connectTimeout:settings.commandTimeoutMs||10000,reconnectStrategy:false}});client.on('error',()=>{});await client.connect();
  const bounded=async fn=>{let t;try{return await Promise.race([fn(),new Promise((_,reject)=>{t=setTimeout(()=>{if(client.isOpen)client.destroy();reject(new Error('REDIS_TIMEOUT'));},settings.commandTimeoutMs||10000);})]);}finally{clearTimeout(t);}};
  return {eval:(...args)=>bounded(()=>client.eval(...args)),ping:()=>bounded(()=>client.ping()),close:()=>{if(client.isOpen)client.destroy();}};
}
