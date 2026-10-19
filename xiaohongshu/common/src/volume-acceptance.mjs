import {createHash} from 'node:crypto';

// Business quantity acceptance, deliberately NOT a quality/recall assessment.
// Every deployment must use an explicit population and zero-threshold policy.
export const VOLUME_POLICY='20261015-keyword-count-p80-v1';
export const PERCENTILE_METHOD='nearest-rank';
const digest=value=>createHash('sha256').update(JSON.stringify(value)).digest('hex');
const count=value=>Number.isSafeInteger(value)&&value>=0;
const required=(value,name)=>{
 if(typeof value!=='string'||!value.trim())throw new Error(`VOLUME_${name}_REQUIRED`);
 return value;
};
const identity=task=>JSON.stringify([task.projectName,task.keyword]);

export function normalizeVolumeTasks(tasks){
 if(!Array.isArray(tasks)||!tasks.length)throw new Error('VOLUME_MANIFEST_EMPTY');
 const ids=new Set(),identities=new Set();
 return tasks.map(task=>{
  const result={taskId:required(task.taskId||task.redisTaskId||task.id,'TASK_ID'),
   keyword:required(task.keyword,'KEYWORD'),projectName:required(task.projectName,'PROJECT')};
  if(ids.has(result.taskId)||identities.has(identity(result)))throw new Error('VOLUME_MANIFEST_DUPLICATE');
  ids.add(result.taskId);identities.add(identity(result));return result;
 });
}

export function percentile80(values){
 if(!Array.isArray(values)||!values.length||values.some(v=>!count(v)))throw new Error('VOLUME_DISTRIBUTION_INVALID');
 const sorted=[...values].sort((a,b)=>a-b),rank=Math.ceil(sorted.length*4/5);
 return {rank,size:sorted.length,value:sorted[rank-1],method:PERCENTILE_METHOD};
}

export function buildVolumeSnapshot({platform,tasks,counts,population='all_keywords',minimumPosts=0,allowZeroCompletion=false,
 checkedAt=new Date().toISOString(),dbReadbackVerified=false}){
 required(platform,'PLATFORM');
 if(!['all_keywords','nonzero_keywords'].includes(population)||![0,1].includes(minimumPosts)
  ||typeof allowZeroCompletion!=='boolean')throw new Error('VOLUME_POLICY_OPTIONS_INVALID');
 if(!Array.isArray(counts))throw new Error('VOLUME_COUNTS_REQUIRED');
 const entries=normalizeVolumeTasks(tasks),observed=new Map();
 for(const row of counts){
  const key=JSON.stringify([row.projectName,row.keyword]);
  if(!count(row.posts)||observed.has(key))throw new Error('VOLUME_GROUPED_COUNTS_INVALID');
  observed.set(key,row.posts);
 }
 for(const task of entries)task.posts=observed.get(identity(task))??0;
 const values=entries.map(t=>t.posts).filter(n=>population==='all_keywords'||n>0);
 const percentile=values.length?percentile80(values):null;
 const threshold=percentile?Math.max(minimumPosts,percentile.value):null;
 const body={policy:VOLUME_POLICY,platform,population,minimumPosts,allowZeroCompletion,
  percentile:.8,percentileMethod:PERCENTILE_METHOD,percentileRank:percentile?.rank??null,
  populationSize:values.length,rawThreshold:percentile?.value??null,threshold,
  manifestTaskCount:entries.length,zeroCount:entries.filter(t=>!t.posts).length,
  dbReadbackVerified:dbReadbackVerified===true,checkedAt,entries,
  subtitleQualityRequired:false,annualEndpointRequired:false,
  acceptanceMeaning:'quantity_only_not_content_quality_or_search_recall'};
 return {...body,snapshotId:digest(body)};
}

export function validateVolumeSnapshot(snapshot,{platform,tasks}={}){
 if(!snapshot||snapshot.policy!==VOLUME_POLICY)throw new Error('VOLUME_POLICY_MISMATCH');
 const {snapshotId,...body}=snapshot;
 if(snapshotId!==digest(body)||!Number.isFinite(Date.parse(snapshot.checkedAt)))throw new Error('VOLUME_SNAPSHOT_INVALID');
 if(snapshot.dbReadbackVerified!==true)throw new Error('VOLUME_DATABASE_READBACK_REQUIRED');
 if(platform&&snapshot.platform!==platform)throw new Error('VOLUME_PLATFORM_MISMATCH');
 const rebuilt=buildVolumeSnapshot({...snapshot,tasks:snapshot.entries,counts:snapshot.entries});
 if(rebuilt.snapshotId!==snapshotId)throw new Error('VOLUME_SNAPSHOT_DISTRIBUTION_INVALID');
 if(tasks){
  const original=normalizeVolumeTasks(tasks);
  if(JSON.stringify(original)!==JSON.stringify(snapshot.entries.map(({posts,...task})=>task)))throw new Error('VOLUME_MANIFEST_MISMATCH');
 }
 return snapshot;
}

export function volumeDecision(snapshot,{taskId,posts,readbackVerified=false,checkedAt=new Date().toISOString()}){
 validateVolumeSnapshot(snapshot);
 const task=snapshot.entries.find(t=>t.taskId===taskId);
 if(!task)throw new Error('VOLUME_TASK_NOT_IN_MANIFEST');
 if(!count(posts)||readbackVerified!==true||!Number.isFinite(Date.parse(checkedAt)))throw new Error('VOLUME_TASK_READBACK_REQUIRED');
 const reason=snapshot.threshold==null?'VOLUME_POPULATION_EMPTY':
  snapshot.threshold===0&&!snapshot.allowZeroCompletion?'VOLUME_ZERO_THRESHOLD_REQUIRES_CHOICE':
  posts>=snapshot.threshold?'VOLUME_THRESHOLD_REACHED':'VOLUME_BELOW_THRESHOLD';
 const blocked=['VOLUME_POPULATION_EMPTY','VOLUME_ZERO_THRESHOLD_REQUIRES_CHOICE'].includes(reason);
 return {policy:VOLUME_POLICY,snapshotId:snapshot.snapshotId,platform:snapshot.platform,
  taskId,keyword:task.keyword,projectName:task.projectName,posts,threshold:snapshot.threshold,
  dbReadbackVerified:true,checkedAt,ok:!blocked&&posts>=snapshot.threshold,
  action:blocked?'requires_policy_choice':posts>=snapshot.threshold?'complete_by_volume':'reset_existing',reason,
  subtitleQualityRequired:false,qualityVerified:false,annualEndpointRequired:false,
  preserveHistory:true,deleteExistingData:false,createNewTask:false,
  acceptanceMeaning:'quantity_only_not_content_quality_or_search_recall'};
}

// The sole source of counts is a read-only SQL transaction. Missing grouped
// rows mean zero ONLY after the complete, successful manifest-scope query.
export async function readVolumeSnapshot({connect,platform,tasks,...policyOptions}){
 const manifest=normalizeVolumeTasks(tasks),projects=[...new Set(manifest.map(t=>t.projectName))];
 const connection=await connect();
 try{
  await connection.query('SET TRANSACTION READ ONLY');await connection.beginTransaction();
  const [rows]=await connection.execute(
   `SELECT \`项目\` AS projectName,\`关键词\` AS keyword,COUNT(DISTINCT NULLIF(TRIM(\`文章id\`),'')) AS posts `+
   `FROM ods_social_media_post WHERE \`平台\`=? AND \`项目\` IN (${projects.map(()=>'?').join(',')}) GROUP BY \`项目\`,\`关键词\``,
   [platform,...projects]);
  const counts=rows.map(r=>({projectName:r.projectName,keyword:r.keyword,posts:Number(r.posts)}));
  const snapshot=buildVolumeSnapshot({platform,tasks:manifest,counts,...policyOptions,
   checkedAt:new Date().toISOString(),dbReadbackVerified:true});
  await connection.commit();return snapshot;
 }catch(error){await connection.rollback().catch(()=>{});throw error;}
 finally{await connection.end();}
}

export async function readTaskVolume({connect,snapshot,taskId}){
 validateVolumeSnapshot(snapshot);
 const task=snapshot.entries.find(t=>t.taskId===taskId);
 if(!task)throw new Error('VOLUME_TASK_NOT_IN_MANIFEST');
 const connection=await connect();
 try{
  await connection.query('SET TRANSACTION READ ONLY');await connection.beginTransaction();
  const [rows]=await connection.execute(
   "SELECT COUNT(DISTINCT NULLIF(TRIM(`文章id`),'')) AS posts FROM ods_social_media_post WHERE `平台`=? AND `项目`=? AND `关键词`=?",
   [snapshot.platform,task.projectName,task.keyword]);
  if(rows.length!==1)throw new Error('VOLUME_TASK_READBACK_INVALID');
  const decision=volumeDecision(snapshot,{taskId,posts:Number(rows[0].posts),readbackVerified:true});
  await connection.commit();return decision;
 }catch(error){await connection.rollback().catch(()=>{});throw error;}
 finally{await connection.end();}
}
