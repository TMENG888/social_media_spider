import {readFileSync} from 'node:fs';
import {collectionNodeFailure} from './collection-failure.mjs';
const SCRIPT=readFileSync(new URL('./reset-once.lua',import.meta.url),'utf8');
export const RECOLLECTION_POLICY='reset-once-20261016-v1';
export function protectedRecollection(record,pause=false){
 return pause||record?.stopped===true||collectionNodeFailure(record).stopNode||/LOGIN_REQUIRED|SECURITY_CHALLENGE|PLATFORM_RESTRICTION|CAPTCHA|STOP_REQUESTED|RATE_LIMIT|COOLDOWN|login_required|risk_controlled|partial_stopped/i.test(String(record?.error||'')+' '+String(record?.previousCollectionError||'')+' '+String(record?.status||''));
}
export function recollectionOutcome(record={}){
 const importOk=record.importOk===true||record.importExitCode===0||record.mysql?.status==='success'||record.importSummary?.readbackVerified===true;
 return {...record,importOk,collectionSucceeded:importOk&&['completed','completed_with_skips'].includes(record.status)&&!record.error&&!record.previousCollectionError,
  // An unsuccessful replay still closes the business task, never its quality claim.
  dataMayRemainLocal:!importOk};
}
export class ResetOncePolicy{
 constructor(queue){this.queue=queue;const q=queue;
  this.keys=[q.namespace+':recollection-once',q.namespace+':recollection-history',q.keys[1],q.keys[2],q.keys[3],q.keys[4],
   q.keys[5],q.keys[6],q.keys[7],q.keys[8],q.keys[9],q.namespace+':volume-attempt-baseline',q.keys[0]];}
 async command(mode,id,{token='',owner='',record={},expected=''}={}){
  return JSON.parse(await this.queue.client.eval(SCRIPT,{keys:this.keys,arguments:[mode,id,'hash',token,owner,'','',''+id,JSON.stringify(record),expected,'300000']}));
 }
 read(id){return this.command('read',id);}
 arm(id,record,expected){return this.command('arm',id,{record,expected});}
 prepare(id){return this.command('prepare',id);}
 async start(id,token){const row=await this.read(id);if(!row.state)return null;return this.command('start',id,{token});}
 async finish(id,token,record,{pause=false}={}){
  const row=await this.read(id);if(!row.state)return null;
  if(row.state==='completed')return this.prepare(id);
  return this.command(protectedRecollection(record,pause)?'pause':'finish',id,{token,record:recollectionOutcome(record)});
 }
}
