// Local control-failure latch recovery only. No task or database operations.
import fs from 'node:fs/promises';
import path from 'node:path';
import {randomUUID} from 'node:crypto';

const names=['supervisor.stop','stop.requested'];
export const recoveryVersion='xhs-control-recovery-20261022-v1';
export function failureCode(error) {
  const code=String(error?.code||'')+' '+String(error?.message||'');
  if(/TIMEOUT|ETIMEDOUT/i.test(code))return 'CONTROL_TIMEOUT';
  if(/WRONGPASS|NOAUTH|AUTH/i.test(code))return 'CONTROL_AUTH_FAILED';
  if(/NOPERM/i.test(code))return 'CONTROL_PERMISSION_DENIED';
  if(/INVALID_STOP_REQUEST|SyntaxError/i.test(code)||error instanceof SyntaxError)return 'CONTROL_INVALID_RESPONSE';
  return 'CONTROL_CONNECTION_OR_IO_ERROR';
}
export function isControlFailure(value,ctx) {
  if(!value||typeof value!=='object'||Array.isArray(value)||value.reason!=='REMOTE_CONTROL_UNAVAILABLE')return false;
  // Two legacy writers emitted exactly these two fields, without an identity.
  if(Object.keys(value).length===2&&['redis_remote_control','remote_control'].includes(value.source))return true;
  const keys=['source','reason','schemaVersion','markerKind','platform','campaign','target','createdAt','failureCode'];
  return Object.keys(value).every(k=>keys.includes(k))&&value.source==='redis_remote_control'&&value.schemaVersion===1&&
    value.markerKind==='control_channel_failure'&&value.target===ctx.target&&value.platform===ctx.platform&&
    value.campaign===ctx.campaign&&Number.isFinite(Date.parse(value.createdAt))&&
    /^CONTROL_[A-Z_]+$/.test(value.failureCode||'');
}
export async function markControlFailure(ctx,error) {
  const state=path.join(ctx.workerRoot,'.state');await fs.mkdir(state,{recursive:true});
  const value={schemaVersion:1,source:'redis_remote_control',markerKind:'control_channel_failure',
    reason:'REMOTE_CONTROL_UNAVAILABLE',platform:ctx.platform,campaign:ctx.campaign,target:ctx.target,
    createdAt:new Date().toISOString(),failureCode:failureCode(error)};
  // Exclusive creation: repeated network failures never replace human/remote stops
  // or alter the original failure time. Even a partial write stays fail-closed.
  for(const name of names){
    let handle;
    try{handle=await fs.open(path.join(state,name),'wx');await handle.writeFile(JSON.stringify(value,null,2),'utf8');}
    catch(error){if(error.code!=='EEXIST')throw error;}
    finally{await handle?.close();}
  }
  return value.failureCode;
}
async function snapshot(file) {
  try{
    const stat=await fs.lstat(file);
    if(!stat.isFile()||stat.isSymbolicLink())throw new Error('CONTROL_RECOVERY_UNSAFE_FILE');
    const bytes=await fs.readFile(file);
    return {file,bytes,stat};
  }catch(error){if(error.code==='ENOENT')return null;throw error;}
}
function same(a,b){return a&&b&&a.bytes.equals(b.bytes)&&a.stat.ino===b.stat.ino&&a.stat.dev===b.stat.dev&&a.stat.mtimeMs===b.stat.mtimeMs;}
async function assertIdle(state) {
  for(const [name,key] of [['worker.lock','pid'],['monitor-supervisor.json','supervisorPid']]){
    const item=await snapshot(path.join(state,name));if(!item)continue;
    let pid;try{pid=JSON.parse(item.bytes.toString('utf8').replace(/^\uFEFF/,''))[key];}catch{}
    if(!Number.isSafeInteger(pid)||pid<=0)throw new Error('CONTROL_RECOVERY_PROCESS_UNKNOWN');
    try{process.kill(pid,0);}
    catch(error){if(error.code==='ESRCH')continue;throw new Error('CONTROL_RECOVERY_PROCESS_UNKNOWN');}
    throw new Error('CONTROL_RECOVERY_NODE_ACTIVE');
  }
}
export async function recoverControlFailure(ctx,verifyNoHold) {
  const state=path.join(ctx.workerRoot,'.state');
  if(await snapshot(path.join(state,'remote-control-recovery.lock')))throw new Error('CONTROL_RECOVERY_INCOMPLETE');
  const items=await Promise.all(names.map(n=>snapshot(path.join(state,n))));
  const owned=item=>{try{return isControlFailure(JSON.parse(item.bytes.toString('utf8').replace(/^\uFEFF/,'')),ctx);}catch{return false;}};
  if(!items.some(item=>item&&owned(item)))return {version:recoveryVersion,archived:[]};
  if(items.some(item=>item&&!owned(item)))throw new Error('CONTROL_RECOVERY_PROTECTED_STOP');
  await assertIdle(state);
  const lockFile=path.join(state,'remote-control-recovery.lock');
  const lock=await fs.open(lockFile,'wx');const moved=[];let restoreFailed=false;
  try{
    await lock.writeFile(JSON.stringify({version:recoveryVersion,target:ctx.target,pid:process.pid,startedAt:new Date().toISOString()}),'utf8');
    await verifyNoHold();await assertIdle(state);
    for(let i=0;i<names.length;i++){
      const current=await snapshot(path.join(state,names[i]));
      if((items[i]||current)&&!same(items[i],current))throw new Error('CONTROL_RECOVERY_MARKER_CHANGED');
    }
    const archive=path.join(state,'remote-control-recovery',new Date().toISOString().replace(/[:.]/g,'-')+'-'+randomUUID());
    await fs.mkdir(archive,{recursive:true});
    for(const item of items.filter(Boolean)){
      const saved=path.join(archive,path.basename(item.file));
      await fs.rename(item.file,saved);moved.push({original:item.file,saved});
      if(!same(item,await snapshot(saved)))throw new Error('CONTROL_RECOVERY_MARKER_CHANGED');
    }
    await verifyNoHold();await assertIdle(state);
    for(const name of names)if(await snapshot(path.join(state,name)))throw new Error('CONTROL_RECOVERY_NEW_STOP');
    return {version:recoveryVersion,archived:moved.map(item=>item.saved)};
  }catch(error){
    // Restore without overwriting any stop that arrived during recovery. Keep
    // all archived evidence, including on rollback or an ambiguous outcome.
    for(const item of moved){try{await fs.link(item.saved,item.original);}catch(restore){
      if(restore.code!=='EEXIST')restoreFailed=true;
    }}
    if(restoreFailed)throw new Error('CONTROL_RECOVERY_RESTORE_REQUIRED');
    throw error;
  }finally{await lock.close();if(!restoreFailed)await fs.unlink(lockFile);}
}
