// Node-local disk recovery only. No Redis, task, SQL or browser operations.
import fs from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import {randomUUID} from 'node:crypto';

export const STORAGE_STOP_VERSION='xhs-local-storage-20261023-v1';
const present=file=>fs.lstat(file).then(()=>true,error=>{if(error.code==='ENOENT')return false;throw error;});
const blocked=(reason,details={})=>({ready:false,reason,...details});
export const isStorageFull=error=>error?.code==='ENOSPC';
export function storageStopMarker({workerId}) {
  return {schemaVersion:1,source:'local_storage_monitor',code:'ENOSPC',workerId,
    machine:os.hostname(),pid:process.pid,createdAt:new Date().toISOString(),version:STORAGE_STOP_VERSION};
}
export function isLocalStorageMarker(raw,workerId) {
  // Compatibility with the old cooldown monitor's exact, bare error code.
  if(raw.trim()==='ENOSPC')return true;
  let m;try{m=JSON.parse(raw);}catch{return false;}
  return m?.schemaVersion===1&&m.source==='local_storage_monitor'&&m.code==='ENOSPC'
    &&m.workerId===workerId&&m.machine===os.hostname()&&m.version===STORAGE_STOP_VERSION
    &&Number.isSafeInteger(m.pid)&&m.pid>0&&typeof m.createdAt==='string'
    &&Number.isFinite(Date.parse(m.createdAt))&&Date.parse(m.createdAt)<=Date.now();
}
async function probeDirectory(directory) {
  const file=path.join(directory,'.storage-probe-'+randomUUID());let handle;
  try{handle=await fs.open(file,'wx');await handle.writeFile(Buffer.alloc(65536));await handle.sync();}
  finally{if(handle){await handle.close();await fs.unlink(file);}}
}
export async function verifyLocalStorage(paths,{statfs=fs.statfs,probe=probeDirectory,minFreeBytes=2n*1024n**3n}={}) {
  const volumes=[];
  for(const directory of new Set(paths.map(p=>path.resolve(p)))) {
    try{
      const s=await statfs(directory,{bigint:true}),freeBytes=BigInt(s.bavail)*BigInt(s.bsize);
      volumes.push({directory,freeBytes:String(freeBytes)});
      if(freeBytes<BigInt(minFreeBytes))return blocked('local_storage_low_space',{volumes,minFreeBytes:String(minFreeBytes)});
      await probe(directory);
    }catch(error){return blocked('local_storage_probe_failed',{directory,errorCode:error.code||'IO_ERROR'});}
  }
  return {ready:true,reason:'local_storage_verified',volumes};
}
async function snapshot(file) {
  try{
    const stat=await fs.lstat(file);
    if(!stat.isFile()||stat.isSymbolicLink()||stat.size>16384)return null;
    return {stat,raw:await fs.readFile(file,'utf8')};
  }catch(error){if(error.code==='ENOENT')return null;throw error;}
}
const same=(a,b)=>a&&b&&a.raw===b.raw&&a.stat.ino===b.stat.ino&&a.stat.dev===b.stat.dev
  &&a.stat.size===b.stat.size&&a.stat.mtimeMs===b.stat.mtimeMs;
async function restore(archive,stopFile) {
  try{await fs.link(archive,stopFile);await fs.unlink(archive);}
  catch(error){if(error.code!=='EEXIST')throw error;}
}
export async function recoverLocalStorageStop({stopFile,supervisorStopFile,workerId,lockFile,
  storagePaths=[path.dirname(stopFile)],verifyStorage=verifyLocalStorage,afterRead,afterMove}) {
  supervisorStopFile ||= path.join(path.dirname(stopFile),'supervisor.stop');
  if(await present(supervisorStopFile))return blocked('supervisor_stop');
  const original=await snapshot(stopFile);
  if(!original||!isLocalStorageMarker(original.raw,workerId))return {ready:true,reason:'not_local_storage_marker'};
  // The caller must hold this worker's exclusive lock; never recover a live peer.
  let lock;try{lock=JSON.parse(await fs.readFile(lockFile,'utf8'));}catch{}
  if(lock?.workerId!==workerId||lock?.pid!==process.pid)return blocked('local_storage_worker_lock_required');
  const health=await verifyStorage(storagePaths);
  if(!health.ready)return health;
  await afterRead?.();
  if(await present(supervisorStopFile))return blocked('supervisor_stop');
  if(!same(original,await snapshot(stopFile)))return blocked('stop_marker_changed');
  const archive=stopFile+'.storage-archived-'+randomUUID();
  try{await fs.rename(stopFile,archive);}catch(error){if(error.code==='ENOENT')return blocked('stop_marker_changed');throw error;}
  try{
    await afterMove?.();
    if(!same(original,await snapshot(archive))){await restore(archive,stopFile);return blocked('stop_marker_changed');}
  }catch(error){await restore(archive,stopFile);throw error;}
  if(await present(stopFile)||await present(supervisorStopFile))return blocked('new_stop_request',{archive});
  return {ready:true,reason:'local_storage_stop_archived',version:STORAGE_STOP_VERSION,archive,volumes:health.volumes};
}
