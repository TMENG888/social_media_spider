// Quantity-only closure after a security restriction; never clears node protection.
import fs from 'node:fs/promises';
import path from 'node:path';
export const RISK_VOLUME_VERSION='risk-volume-close-20261105-v1';
export async function riskStopGate(stateRoot) {
 for(const name of ['supervisor.stop','stop.requested']) {
  try {const marker=await fs.readFile(path.join(stateRoot,name),'utf8');
   if(name!=='stop.requested'||marker.trim()!=='RATE_LIMIT_COOLDOWN_ACTIVE')return false;
  }catch(error){if(error.code!=='ENOENT')return false;}
 }
 return true;
}
export function riskVolumeEvidence(record={}) {
 const text=[record.collectionError,record.previousCollectionError,record.error].filter(Boolean).join(' | ');
 if(!/SECURITY_CHALLENGE|PLATFORM_RESTRICTION|300013|安全限制|访问过于频繁|操作频繁/.test(text))return null;
 if(/LOGIN_REQUIRED|login_required|CAPTCHA|captcha|验证码|滑块|拼图|安全验证|请完成.*验证|STOP_REQUESTED|LEASE_LOST|CONTROL_|REMOTE_CONTROL|ENOSPC/.test(text))return null;
 if(record.riskVolumeStopApproved!==true||record.pendingImport===true||record.importError||record.importOk===false)return null;
 if(record.importExitCode!=null&&record.importExitCode!==0)return null;
 if(!(record.importOk===true||record.importExitCode===0))return null;
 if(Array.isArray(record.imports)&&record.imports.some(row=>row.status!=='imported'&&Number(row.count)>0))return null;
 return {policy:RISK_VOLUME_VERSION,kind:'security',originalError:text.slice(0,2000),importVerified:true,
  stopApproved:true,pendingImport:false,qualityVerified:false};
}
export async function completeRiskVolume(runtime,taskId,token,record) {
 const evidence=riskVolumeEvidence(record);if(!evidence)return null;
 if(!await runtime.canCompleteRisk?.())return null;
 // Read SQL only after the current task's preservation import succeeded.
 const decision=await runtime.read(taskId);if(!decision.ok)return null;
 if(!await runtime.canCompleteRisk?.())return null;
 const confirmation=await runtime.apply(decision,{token,commit:true,riskEvidence:evidence});
 return confirmation.acceptedByRiskVolume?{decision,confirmation,riskVolumeEvidence:evidence}:null;
}
