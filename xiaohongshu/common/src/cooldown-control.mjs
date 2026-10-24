import fs from 'node:fs/promises';
import path from 'node:path';
import {RateLimitCooldown} from './rate-limit-cooldown.mjs';
import {COOLDOWN_SCOPE_VERSION} from './cooldown-scope.mjs';
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
  console.log(`[保护作用域] ${COOLDOWN_SCOPE_VERSION}；本节点=${queue.workerId}；登录/验证码按机器节点隔离。`);
  if(args.action==='reset-confirmed'){
    await controller.resetConfirmed();
    console.log('[Cooldown] Manual confirmation recorded. Shared cooldown reset; no tasks/database/checkpoints changed.');
  }else{
    let announced='';
    const result=await controller.wait({shouldStop,waitForManual:true,onState:s=>{
      const key=`${s.lastIncidentAt}-${s.nodeIncidentId}-${s.scope}-${s.active}-${s.manualRequired}`;
      if(key===announced)return;announced=key;
      if(s.manualRequired)console.warn(s.scope==='node'
        ?`[节点等待] 小红书 / ${queue.workerId} / ${s.nodeKind||'manual'}；仅本机节点等待人工处理并确认，不阻塞其他节点。`
        :'[共享保护] 来源不明或明确组级的人工保护仍有效，需单独核查；不会自动解除。');
      else if(s.active)console.log(`[Cooldown] Round ${s.count}; resume no earlier than ${new Date(s.untilMs).toLocaleString('zh-CN')}. No platform access while waiting. Safe-stop BAT cancels resume.`);
    }});
    process.exitCode=result.stopped?20:result.manual?21:0;
    if(result.ready&&!await shouldStop()){
      const ownStop=path.join(stateRoot,'stop.requested');
      try{
        const before=await fs.stat(ownStop),text=await fs.readFile(ownStop,'utf8');
        const after=await fs.stat(ownStop);
        if(['RATE_LIMIT_COOLDOWN_ACTIVE','COOLDOWN_MANUAL_REQUIRED'].includes(text)&&before.mtimeMs===after.mtimeMs&&before.size===after.size)
          await fs.unlink(ownStop);
      }catch(e){if(e.code!=='ENOENT')throw e;}
    }
  }
}catch(error){console.warn(error.message);process.exitCode=1;}
finally{await controller?.close();}
