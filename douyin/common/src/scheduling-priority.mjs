import fs from 'node:fs/promises';
import path from 'node:path';
import {scopedTasks} from './task-scope.mjs';

const DONE=new Set(['completed','completed_with_skips','skipped_unresolved']);
// Keep priority outside immutable task payloads: IDs, attempts and checkpoints
// survive a scheduling change. A leased priority task also holds back later brands.
export async function schedulingPlan(root,tasks,queue){
 const eligible=await scopedTasks(root,tasks);
 let config;
 try{config=JSON.parse((await fs.readFile(path.join(root,'task-scope.json'),'utf8')).replace(/^\uFEFF/,''));}
 catch(e){if(e.code==='ENOENT')return {tasks:eligible,priorityActive:false};throw e;}
 const words=config.enabled===false?null:config.priorityKeywords;
 if(words==null||Array.isArray(words)&&!words.length)return {tasks:eligible,priorityActive:false};
 if(!Array.isArray(words)||words.some(w=>typeof w!=='string'||!w)||new Set(words).size!==words.length)throw new Error('TASK_PRIORITY_INVALID');
 const map=new Map(eligible.map(t=>[t.keyword,t]));
 if(words.some(w=>!map.has(w)))throw new Error('TASK_PRIORITY_NOT_IN_SCOPE');
 const priority=words.map(w=>map.get(w));
 const statuses=await Promise.all(priority.map(t=>queue.inspect(t.redisTaskId||t.id)));
 if(statuses.some(s=>!DONE.has(s.status)))return {tasks:priority,priorityActive:true,label:config.priorityLabel||'优先品牌'};
 return {tasks:eligible,priorityActive:false,label:config.priorityLabel||'优先品牌'};
}
