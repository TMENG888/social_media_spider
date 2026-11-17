import fs from 'node:fs/promises';
import {createHash} from 'node:crypto';
export const RECONCILIATION_POLICY='closed_keyword_blank_fields_and_explicit_gaps_v1';
const allowedFields=new Set(['文章内容','文章视频内容']);
export const isBlank=value=>value==null||String(value).trim()==='';
export const businessKey=key=>JSON.stringify(key);
export function validateFields(fields){
 const seen=new Set();for(const f of fields){if(!allowedFields.has(f.field)||f.platform!=='小红书'||!f.articleId||!f.project||isBlank(f.value))throw new Error('INVALID_PATCH_FIELD');
  if(f.field==='文章视频内容'&&!f.identityVerified)throw new Error('UNVERIFIED_SUBTITLE_SOURCE');
  const k=JSON.stringify([f.articleId,f.platform,f.project,f.field]);if(seen.has(k))throw new Error('DUPLICATE_PATCH_FIELD');seen.add(k);}
}
export async function durableAppend(file,value){const h=await fs.open(file,'a');try{await h.writeFile(JSON.stringify(value)+'\n');await h.sync();}finally{await h.close();}}
export async function fillEmptyFields({fields,connect,queryLock,retry,archive,onBatch=async()=>{}}){
 validateFields(fields);const results=[];
 for(let offset=0;offset<fields.length;offset+=5){const batch=fields.slice(offset,offset+5);
  const committed=await retry(async()=>{const c=await connect();let acquired=false,transaction=false;const changes=[];
   try{const [lock]=await queryLock(c);if(Number(lock[0]?.acquired)!==1)throw Object.assign(new Error('LOCK_BUSY'),{code:'MYSQL_IMPORT_LOCK_TIMEOUT'});acquired=true;
    await c.query({sql:'SET SESSION innodb_lock_wait_timeout=15',timeout:30000});await c.beginTransaction();transaction=true;
    for(const f of batch){
     const [rows]=await c.execute({sql:`SELECT \`id\`,\`${f.field}\` AS value FROM \`ods_social_media_post\` WHERE \`文章id\`=? AND \`平台\`=? AND \`项目\`=? FOR UPDATE`,timeout:30000},[f.articleId,f.platform,f.project]);
     if(rows.length!==1)throw new Error('PATCH_IDENTITY_NOT_UNIQUE');const row=rows[0];
     if(!isBlank(row.value)){changes.push({articleId:f.articleId,field:f.field,action:'preserved_nonempty',length:String(row.value).length});continue;}
     await archive({event:'before_empty_field_patch',at:new Date().toISOString(),rowId:String(row.id),articleId:f.articleId,field:f.field,before:row.value,after:f.value,sourceFile:f.sourceFile,sourceUpdatedAt:f.sourceUpdatedAt});
     const [updated]=await c.execute({sql:`UPDATE \`ods_social_media_post\` SET \`${f.field}\`=? WHERE \`id\`=? AND (\`${f.field}\` IS NULL OR TRIM(\`${f.field}\`)='')`,timeout:30000},[f.value,String(row.id)]);
     if(updated.affectedRows!==1)throw new Error('PATCH_COMPARE_FAILED');changes.push({articleId:f.articleId,field:f.field,action:'filled_empty',length:String(f.value).length,sha256:createHash('sha256').update(f.value).digest('hex')});
    }
    await c.commit();transaction=false;return changes;
   }catch(e){if(transaction)await c.rollback().catch(()=>{});throw e;}finally{if(acquired)await c.query({sql:"SELECT RELEASE_LOCK('social_xhs_distributed_import')",timeout:10000}).catch(()=>{});await c.end().catch(()=>{});}
  });results.push(...committed);await onBatch({offset,committed});
 }
 return results;
}
export function coverageEvidence(task,existing){
 const coverage={};let acceptable=true;
 for(const kind of ['posts','comments']){
  const missing=task[kind].filter(k=>!existing[kind].has(businessKey(k))),allowed=new Set((task.allowedMissing[kind]||[]).map(businessKey));
  if(missing.some(k=>!allowed.has(businessKey(k))))acceptable=false;
  coverage[kind]={localDistinct:task[kind].length,present:task[kind].length-missing.length,missing,acceptedMissing:missing.length};
 }
 return {ok:acceptable,coverage,hasAcceptedGaps:coverage.posts.missing.length+coverage.comments.missing.length>0};
}
export const CONFIRM_LUA=`
local id,expected,replacement,receipt=ARGV[1],ARGV[2],ARGV[3],ARGV[4]
for i,key in ipairs(KEYS) do local probe=redis.pcall('HLEN',key);if type(probe)=='table' and probe.err then return redis.error_reply('RECONCILE_KEY_TYPE') end end
if redis.call('HGET',KEYS[1],id)~=expected then return cjson.encode({ok=false,reason='RESULT_CHANGED'}) end
if redis.call('HGET',KEYS[2],id)~='completed' then return cjson.encode({ok=false,reason='NOT_CLOSED'}) end
local prior=cjson.decode(expected);local next=cjson.decode(replacement);local proof=cjson.decode(receipt)
if prior.pendingImport~=true or next.pendingImport~=false or next.keyword~=prior.keyword or next.projectName~=prior.projectName or next.acceptedBy~=prior.acceptedBy or proof.ok~=true then return redis.error_reply('RECONCILE_EVIDENCE_INVALID') end
if redis.call('HEXISTS',KEYS[4],id)==1 then return redis.error_reply('RECONCILE_ARCHIVE_EXISTS') end
local t=redis.call('TIME');proof.confirmedAtMs=tonumber(t[1])*1000+math.floor(tonumber(t[2])/1000)
next.importReconciliation=proof
redis.call('HSET',KEYS[4],id,cjson.encode({previousResult=expected,receipt=proof}))
redis.call('HSET',KEYS[1],id,cjson.encode(next));redis.call('HDEL',KEYS[3],id)
return cjson.encode({ok=true,keyword=next.keyword,confirmedAtMs=proof.confirmedAtMs})
`;
export async function confirmClosedImport({client,namespace,task,receipt,runId,archive}){
 if(!receipt.ok||receipt.policy!==RECONCILIATION_POLICY)throw new Error('INVALID_IMPORT_RECEIPT');
 const raw=await client.hGet(namespace+':results',task.taskId);if(!raw)throw new Error('RESULT_MISSING');const prior=JSON.parse(raw);
 if(prior.keyword!==task.keyword||prior.projectName!==task.projectName||prior.acceptedBy!=='local_posts_p80_on_exception')throw new Error('RESULT_IDENTITY_MISMATCH');
 if(prior.pendingImport===false)return {ok:true,alreadyConfirmed:true,keyword:task.keyword};
 const replacement={...prior,pendingImport:false,importStatus:receipt.hasAcceptedGaps?'verified_with_accepted_gaps':'verified',importOk:!receipt.hasAcceptedGaps};
 await archive({event:'before_redis_import_reconciliation',taskId:task.taskId,previousResult:raw,receipt});
 return JSON.parse(await client.eval(CONFIRM_LUA,{keys:[namespace+':results',namespace+':statuses',namespace+':local-p80-pending-imports',namespace+':import-reconciliation-history:'+runId],arguments:[task.taskId,raw,JSON.stringify(replacement),JSON.stringify(receipt)]}));
}
