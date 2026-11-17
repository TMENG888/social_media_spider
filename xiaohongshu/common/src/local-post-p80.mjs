import {createHash} from 'node:crypto';
import {LOCAL_P80_REFRESH_POLICY} from './local-p80-refresh.mjs';

export const LOCAL_P80_POLICY='xhs-local-posts-p80-on-exception-20261107-v1';
const digest=s=>createHash('sha256').update(String(s)).digest('hex');
export const localP80Keys=(namespace,keyword)=>[namespace+':local-p80-meta',namespace+':local-p80-counts',namespace+':local-p80-posts:'+digest(keyword)];
const TYPES=`
local function probe(key,kind)
 if kind=='zset' then redis.call('ZSCORE',key,'__local_p80_probe__') else redis.call('HGET',key,'__local_p80_probe__') end
 return true
end
`;
export function localP80Exception(record={}){
 if(record.collectionStatus==='lease_lost'||record.status==='lease_lost'||/^STOP_LEASE_LOST/.test(record.collectionError||record.error||''))return null;
 if(Number.isInteger(record.importExitCode)&&record.importExitCode!==0)return 'import_failure';
 const status=record.collectionStatus||record.status,error=String(record.collectionError||record.error||'');
 if(status==='partial_stopped'||/^STOP_REQUESTED/.test(error))return null;
 if(['partial_error','login_required','risk_controlled','web_unavailable','browser_closed','failure_threshold','sort_unconfirmed','context_lost','import_pending','import_failed'].includes(status))return 'collection_exception';
 return null;
}
export function savedPostIdentity(post,keyword){
 if(!post||typeof post!=='object')return null;
 const id=String(post['文章id']||'').trim(),k=String(post['关键词']||keyword||'').trim();
 if(!id||k!==keyword)return null;
 if(post['平台']&&!['小红书','xhs','xiaohongshu'].includes(String(post['平台']).toLowerCase()))return null;
 return id;
}
// Each hash contains article IDs actually saved on at least one cluster node.
// Replays, overlapping date windows and cross-node copies do not increase HLEN.
export async function recordLocalPosts(client,namespace,keyword,ids){
 if(!ids.length)return;
 const keys=localP80Keys(namespace,keyword);
 for(let offset=0;offset<ids.length;offset+=500){
  await client.eval(TYPES+`
if not probe(KEYS[1],'hash') or not probe(KEYS[2],'hash') or not probe(KEYS[3],'hash') then return redis.error_reply('LOCAL_P80_KEY_TYPE') end
if redis.call('HEXISTS',KEYS[2],ARGV[1])==0 then return 0 end
for i=2,#ARGV do redis.call('HSET',KEYS[3],ARGV[i],1) end
local n=redis.call('HLEN',KEYS[3]);redis.call('HSET',KEYS[2],ARGV[1],n);return n`,{keys,arguments:[keyword,...ids.slice(offset,offset+500)]});
 }
}
export async function initializeLocalP80(client,namespace,manifest,baseline){
 const groups=[...new Set(manifest.tasks.map(t=>t.keyword))].sort();
 if(baseline.manifestHash!==manifest.manifestHash||JSON.stringify(Object.keys(baseline.groups).sort())!==JSON.stringify(groups)||
  JSON.stringify([...baseline.sources].sort())!==JSON.stringify(['work01','work02','work03','work04']))throw new Error('LOCAL_P80_BASELINE_INCOMPLETE');
 for(const ids of Object.values(baseline.groups))if(!Array.isArray(ids)||ids.some(id=>typeof id!=='string'||!id.trim()))throw new Error('LOCAL_P80_BASELINE_INVALID');
 const keys=localP80Keys(namespace,'').slice(0,2);
 await client.eval(TYPES+`
if not probe(KEYS[1],'hash') or not probe(KEYS[2],'hash') then return redis.error_reply('LOCAL_P80_KEY_TYPE') end
local old=redis.call('HGET',KEYS[1],'manifestHash')
if old and old~=ARGV[1] then return redis.error_reply('LOCAL_P80_MANIFEST_CHANGED') end
redis.call('HSET',KEYS[1],'manifestHash',ARGV[1],'policy',ARGV[2])
for i=3,#ARGV do if redis.call('HEXISTS',KEYS[2],ARGV[i])==0 then redis.call('HSET',KEYS[2],ARGV[i],0) end end
return 1`,{keys,arguments:[manifest.manifestHash,LOCAL_P80_POLICY,...groups]});
 for(const keyword of groups)await recordLocalPosts(client,namespace,keyword,baseline.groups[keyword]);
 await client.eval(`redis.call('HSET',KEYS[1],'ready',ARGV[1],'sources','work01,work02,work03,work04');return 1`,{keys:[keys[0]],arguments:[manifest.manifestHash]});
 return readLocalP80(client,namespace,manifest.manifestHash,groups[0]);
}
const SNAPSHOT=`
local ready=redis.call('HGET',KEYS[12],'ready')
if not ready or ready~=ARGV[3] or redis.call('HGET',KEYS[12],'policy')~='${LOCAL_P80_POLICY}' then return cjson.encode({ok=false,reason='LOCAL_P80_NOT_READY'}) end
local values=redis.call('HVALS',KEYS[13]);local samples={}
for _,raw in ipairs(values) do local n=tonumber(raw);if not n or n<0 then return redis.error_reply('LOCAL_P80_COUNT_INVALID') end;if n>0 then table.insert(samples,n) end end
if #samples==0 then return cjson.encode({ok=false,reason='LOCAL_P80_EMPTY'}) end
table.sort(samples);local threshold=samples[math.ceil(#samples*4/5)]
local refreshPolicy=redis.call('HGET',KEYS[12],'refreshPolicy')
local snapshotVersion=tonumber(redis.call('HGET',KEYS[12],'thresholdSnapshotVersion')) or 0
local thresholdRefreshedAtMs=tonumber(redis.call('HGET',KEYS[12],'thresholdRefreshedAtMs')) or 0
local sampleSize=#samples
if refreshPolicy=='${LOCAL_P80_REFRESH_POLICY}' then
 threshold=tonumber(redis.call('HGET',KEYS[12],'frozenThreshold'))
 sampleSize=tonumber(redis.call('HGET',KEYS[12],'frozenSamples'))
 if not threshold or threshold<1 or not sampleSize or sampleSize<1 then return redis.error_reply('LOCAL_P80_FROZEN_SNAPSHOT_INVALID') end
end
local count=redis.call('HLEN',KEYS[14]);local qualifies=count>0 and count>=threshold
`;
const COMPLETE=TYPES+`
for i,key in ipairs(KEYS) do
 local kind=(i==6 or i==7 or i==10) and 'zset' or 'hash'
 if not probe(key,kind) then return redis.error_reply('LOCAL_P80_KEY_TYPE') end
end
local id,token,manifest,keyword=ARGV[1],ARGV[2],ARGV[3],ARGV[4]
local record=cjson.decode(ARGV[5]);local trigger=ARGV[6]
if trigger~='import_failure' and trigger~='collection_exception' then return redis.error_reply('LOCAL_P80_EXCEPTION_REQUIRED') end
local payload=redis.call('HGET',KEYS[1],id);local task=payload and cjson.decode(payload) or nil
if not task or task.keyword~=keyword or record.keyword~=keyword or record.projectName~=task.projectName then return redis.error_reply('LOCAL_P80_IDENTITY_MISMATCH') end
local status=redis.call('HGET',KEYS[2],id)
local prior=redis.call('HGET',KEYS[15],id)
if status=='completed' and prior then
 local p=cjson.decode(prior)
 if p.token==token and p.runId==record.runId and redis.call('HGET',KEYS[8],id)==p.completedResult then return cjson.encode({status='completed',changed=false,acceptedByLocalP80=true,evidence=p.evidence}) end
 return redis.error_reply('LOCAL_P80_CONFIRMATION_CONFLICT')
end
local t=redis.call('TIME');local now=tonumber(t[1])*1000+math.floor(tonumber(t[2])/1000)
local expiry=tonumber(redis.call('ZSCORE',KEYS[7],id))
if token=='' or status~='leased' or redis.call('HGET',KEYS[4],id)~=token or not expiry or expiry<=now then return redis.error_reply('LEASE_LOST') end
`+SNAPSHOT+`
if not qualifies then return cjson.encode({ok=false,reason='LOCAL_P80_BELOW_THRESHOLD',posts=count,threshold=threshold,samples=sampleSize}) end
local evidence={policy='${LOCAL_P80_POLICY}',platform='小红书',grouping='platform_only',samplePolicy='nonzero_keywords',
 keyword=keyword,posts=count,threshold=threshold,samples=sampleSize,checkedAtMs=now,clock='redis',trigger=trigger,manifestHash=manifest,
 refreshPolicy=refreshPolicy or false,thresholdSnapshotVersion=snapshotVersion,thresholdRefreshedAtMs=thresholdRefreshedAtMs}
record.status='completed';record.accepted=true;record.businessCompleted=true;record.acceptedBy='local_posts_p80_on_exception'
record.localP80Acceptance=evidence;record.pendingImport=record.importExitCode~=0;record.importOk=record.importExitCode==0
record.allItemsCollected=false
local result=cjson.encode(record)
local archive=cjson.encode({token=token,runId=record.runId,completedResult=result,evidence=evidence,
 previousResult=redis.call('HGET',KEYS[8],id) or false,previousError=redis.call('HGET',KEYS[9],id) or false,at=now})
-- All types, identity, lease and quantities have been checked before any write.
redis.call('HSET',KEYS[15],id,archive)
if record.pendingImport then redis.call('HSET',KEYS[16],id,result) end
redis.call('HSET',KEYS[8],id,result);redis.call('HSET',KEYS[2],id,'completed')
redis.call('ZREM',KEYS[6],id);redis.call('ZREM',KEYS[7],id);redis.call('ZREM',KEYS[10],id)
redis.call('HDEL',KEYS[4],id);redis.call('HDEL',KEYS[5],id)
return cjson.encode({status='completed',changed=true,acceptedByLocalP80=true,evidence=evidence,pendingImport=record.pendingImport})
`;
export async function readLocalP80(client,namespace,manifestHash,keyword){
 const k=localP80Keys(namespace,keyword);
 const script=SNAPSHOT+`return cjson.encode({ok=true,qualifies=qualifies,posts=count,threshold=threshold,samples=sampleSize,grouping='platform_only',refreshPolicy=refreshPolicy or false,thresholdSnapshotVersion=snapshotVersion,thresholdRefreshedAtMs=thresholdRefreshedAtMs})`;
 // The snapshot script uses the same key positions as the fenced commit.
 const keys=Array(11).fill(k[0]);keys.push(...k);
 return JSON.parse(await client.eval(script,{keys,arguments:['','',manifestHash,keyword]}));
}
export async function completeLocalP80(queue,manifestHash,taskId,token,record){
 const trigger=localP80Exception(record);if(!trigger)return {ok:false,reason:'LOCAL_P80_EXCEPTION_REQUIRED'};
 const keys=[...queue.keys,...localP80Keys(queue.namespace,record.keyword),queue.namespace+':local-p80-completion-history',queue.namespace+':local-p80-pending-imports'];
 return JSON.parse(await queue.client.eval(COMPLETE,{keys,arguments:[taskId,token,manifestHash,record.keyword,JSON.stringify(record),trigger]}));
}
