import {probeRedisNetwork} from './redis-network-status.mjs';
// One fresh, bounded verification attempt. The supervisor owns retry delays.
import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {controlContext,connectControl,controlCommand,parseRequest} from './remote-stop-control.mjs';
import {inspectControlFailure,recoverControlFailure,markControlFailure,failureCode} from './remote-control-recovery.mjs';

export async function verifyRecovery(ctx,root){
  let client,gate;
  try{
    client=await connectControl(ctx);
    const raw=await controlCommand(client,ctx,'HGET','stop-requests',[ctx.target]);
    if(parseRequest(raw,ctx))throw new Error('REMOTE_STOP_HOLD');
    if(ctx.platform==='小红书'){
      const {RateLimitCooldown}=await import('./rate-limit-cooldown.mjs');
      // Read and retain protection, including node login/CAPTCHA and timed holds.
      gate=await RateLimitCooldown.open({root,stateRoot:null,workerId:ctx.worker,campaign:ctx.campaign});
    }else{
      const {OperationalGate}=await import('./operational-gate.mjs');
      gate=await OperationalGate.open({root,workerId:ctx.worker,platform:ctx.platform});
    }
    const state=await gate.read();
    if(!state||typeof state!=='object')throw new Error('CONTROL_RECOVERY_INVALID_PROTECTION');
    // A second authoritative stop read closes the protection-read interval.
    if(parseRequest(await controlCommand(client,ctx,'HGET','stop-requests',[ctx.target]),ctx))throw new Error('REMOTE_STOP_HOLD');
  }finally{
    try{await gate?.close();}finally{if(client?.isOpen)client.destroy();}
  }
}
export async function main(args){
  const ctx=await controlContext(args.root,args['worker-root']);
  if(args.action==='mark'){
    await markControlFailure(ctx,{code:args.code});return 0;
  }
  const inspected=await inspectControlFailure(ctx);
  if(inspected.protectedStops.length){console.log('[Connection recovery] Protected stop retained.');return 20;}
  if(!inspected.eligible)return 0;
  if(args.action==='inspect')return 10;
  if(args.action!=='recover')throw new Error('EXPLICIT_ACTION_REQUIRED');
  const owner=args['supervisor-pid']?{pid:Number(args['supervisor-pid']),sessionId:args.session}:null;
  if(owner&&(!Number.isSafeInteger(owner.pid)||!owner.sessionId))throw new Error('CONTROL_RECOVERY_OWNER_REQUIRED');
  const network=await probeRedisNetwork(ctx.settings);
  if(network.state==='offline'){
    console.log('[Connection recovery] LAN route is disconnected; waiting for network, Redis retry budget unchanged.');return 40;
  }
  try{
    const result=await recoverControlFailure(ctx,()=>verifyRecovery(ctx,args.root),{owner});
    const after=await inspectControlFailure(ctx);
    if(after.eligible||after.protectedStops.length)throw new Error('CONTROL_RECOVERY_NEW_STOP');
    const event={at:new Date().toISOString(),event:'connection_recovered',version:result.version,
      archived:result.archived.length,retained:result.retained||[],leasePolicy:'claim_new_lease'};
    await fs.appendFile(path.join(ctx.workerRoot,'.state','connection-recovery.jsonl'),JSON.stringify(event)+'\n');
    console.log('[Connection recovery] Verified; failure flags archived. Original protection and fresh task lease required.');return 0;
  }catch(error){
    if(error.message==='REMOTE_STOP_HOLD'||/CONTROL_RECOVERY_(PROTECTED_STOP|NEW_STOP|SUPERVISOR_CHANGED|NODE_ACTIVE|PROCESS_UNKNOWN|INCOMPLETE|RESTORE_REQUIRED|MARKER_CHANGED)/.test(error.message)){
      console.log('[Connection recovery] Stop or process state changed; recovery blocked.');return 20;
    }
    // A route that dropped during verification does not spend a service retry.
    if((await probeRedisNetwork(ctx.settings)).state==='offline'){
      console.log('[Connection recovery] LAN disconnected during verification; waiting for network.');return 40;
    }
    console.log('[Connection recovery] Verification failed; flags retained ('+failureCode(error)+').');return 30;
  }
}
if(process.argv[1]&&path.resolve(process.argv[1])===fileURLToPath(import.meta.url)){
  const a={};for(let i=2;i<process.argv.length;i+=2)a[process.argv[i].replace(/^--/,'')]=process.argv[i+1];
  try{process.exitCode=await main(a);}catch{console.error('[Connection recovery] Local state unavailable; no flags cleared.');process.exitCode=20;}
}
