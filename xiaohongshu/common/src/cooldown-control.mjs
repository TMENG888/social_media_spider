import fs from 'node:fs/promises';
import path from 'node:path';
import {RateLimitCooldown} from './rate-limit-cooldown.mjs';
const args=Object.fromEntries(process.argv.slice(2).filter((_,i)=>i%2===0).map((k,i)=>[k.slice(2),process.argv[3+i*2]]));
const root=path.resolve(args.root || process.env.XHS_WORKER_ROOT || '.');
const workerRoot=path.resolve(args['worker-root']);
const queuePath=path.join(workerRoot,'tasks','task-queue.json');
const queue=JSON.parse(await fs.readFile(queuePath,'utf8'));
const stateRoot=path.resolve(path.dirname(queuePath),queue.stateRoot || path.join(workerRoot,'.state'));
const stopFile=process.env.XHS_SUPERVISOR_STOP_FILE || path.join(workerRoot,'.state','supervisor.stop');
const shouldStop=()=>fs.access(stopFile).then(()=>true).catch(()=>false);
let controller;
try {
  controller=await RateLimitCooldown.open({root,stateRoot,workerId:queue.workerId});
  if(args.action==='reset-confirmed'){
    await controller.resetConfirmed();
    console.log('[Cooldown] Manual confirmation recorded. Shared cooldown reset; no tasks/database/checkpoints changed.');
  }else{
    let announced='';
    const result=await controller.wait({shouldStop,onState:s=>{
      const key=`${s.lastIncidentAt}-${s.active}-${s.manualRequired}`;
      if(key===announced)return;announced=key;
      if(s.manualRequired)console.warn('[Cooldown] Manual review required. Automatic resume disabled.');
      else if(s.active)console.log(`[Cooldown] Round ${s.count}; resume no earlier than ${new Date(s.untilMs).toLocaleString('zh-CN')}. No platform access while waiting. Safe-stop BAT cancels resume.`);
    }});
    process.exitCode=result.stopped?20:result.manual?21:0;
  }
}catch(error){console.warn(error.message);process.exitCode=1;}
finally{await controller?.close();}
