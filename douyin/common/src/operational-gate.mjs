import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {createHash} from 'node:crypto';
import {redisSettings,connectRedis} from './redis-connection.mjs';
const script=await fs.readFile(new URL('./operational-incident.lua',import.meta.url),'utf8');
export const MONITOR_KEYS=['{collector-monitor-v1}:incidents','{collector-monitor-v1}:outbox'];
export function classifyRestriction(error){
 const text=String(error?.message||error||'');
 if(/LOGIN_REQUIRED|login_required|请先登录|请人工登录|扫码登录/.test(text))return {kind:'login',requiresHuman:true};
 if(/验证码|滑块|拼图|请完成.*验证|安全验证|验证弹窗|captcha/i.test(text))return {kind:'captcha',requiresHuman:true};
 if(/SECURITY_CHALLENGE|PLATFORM_RESTRICTION|访问频繁|操作频繁|访问过于频繁|300013|安全限制|网络环境存在风险|暂时无法浏览/.test(text))return {kind:'security',requiresHuman:false};
 return null;
}
export class OperationalGate{
 static async open({root,workerId,platform,onStage=()=>{}}){
  onStage('READ_REDIS_SETTINGS');
  const settings=await redisSettings(root);
  onStage('READ_REDIS_CONFIG');
  const config=JSON.parse((await fs.readFile(path.join(root,'redis-config.json'),'utf8')).replace(/^\uFEFF/,''));
  onStage('READ_MANIFEST');
  const manifest=JSON.parse((await fs.readFile(path.join(root,'tasks','redis-tasks.json'),'utf8')).replace(/^\uFEFF/,''));
  onStage('VALIDATE_MANIFEST');
  if(!config.taskPoolCampaign&&(typeof manifest.manifestHash!=='string'||!manifest.manifestHash))
   throw Object.assign(new Error('Invalid manifest'),{code:'INVALID_MANIFEST'});
  const campaign=config.taskPoolCampaign||settings.campaign+'-mysql-'+manifest.manifestHash.slice(0,16);
  const namespace='xhs:douyin:{'+campaign+'}';
  onStage('CONNECT_REDIS');
  const client=await connectRedis(settings);
  return new OperationalGate({client,workerId,platform,ownsClient:true,keys:[namespace+':monitor:incidents',namespace+':monitor:outbox']});
 }
 constructor({client,workerId,platform,machine=os.hostname(),ownsClient=false,keys=MONITOR_KEYS}){
  Object.assign(this,{client,workerId,platform,machine,ownsClient,keys});
  this.field=createHash('sha256').update([platform,machine,workerId].join('|')).digest('hex');
 }
 async call(action,value='',cooldownMs=7200000){
  return JSON.parse(await this.client.eval(script,{keys:this.keys,arguments:[action,this.field,typeof value==='string'?value:JSON.stringify(value),String(cooldownMs)]}));
 }
 read(){return this.call('read');}
 async record(error,{taskId='',keyword='',cooldownMs=7200000}={}){
  const restriction=classifyRestriction(error);if(!restriction)return null;
  return this.call('record',{...restriction,field:this.field,platform:this.platform,machine:this.machine,
   workerId:this.workerId,taskId:String(taskId).slice(0,180),keyword:String(keyword).slice(0,180)},cooldownMs);
 }
 resolve(reason='operator_confirmed'){return this.call('resolve',reason);}
 async wait({shouldStop=async()=>false,pollMs=3000}={}){
  let announced='';
  while(!await shouldStop()){
   const state=await this.read();
   if(state.status==='ready'||state.status==='resolved'||(!state.requiresHuman&&state.cooldownUntil<=state.serverTime))return {ready:true,state};
   if(announced!==state.incidentId){console.log('[平台等待] '+this.platform+' / '+this.workerId+' / '+state.kind+(state.requiresHuman?'；等待人工处理并确认':'；冷却后自动探测'));announced=state.incidentId;}
   await new Promise(r=>setTimeout(r,pollMs));
  }
  return {stopped:true};
 }
 async assertReady(){
  const s=await this.read();
  if(s.status==='ready'||s.status==='resolved'||(!s.requiresHuman&&s.cooldownUntil<=s.serverTime))return s;
  throw Object.assign(new Error('OPERATIONAL_HOLD'),{code:'OPERATIONAL_HOLD',state:s});
 }
 async close(){if(this.ownsClient)await this.client.close();}
}
if(process.argv[1]&&path.resolve(process.argv[1])===fileURLToPath(import.meta.url)){
 const a={};for(let i=2;i<process.argv.length;i+=2)a[process.argv[i].replace(/^--/,'')]=process.argv[i+1];
 const gate=await OperationalGate.open({root:a.root,workerId:path.basename(a['worker-root']),platform:a.platform});
 try{
  if(a.action==='resolve')console.log(JSON.stringify(await gate.resolve()));
  else {const stop=()=>fs.access(path.join(a['worker-root'],'.state','supervisor.stop')).then(()=>true,()=>false);
   const r=await gate.wait({shouldStop:stop});process.exitCode=r.stopped?20:0;}
 }finally{await gate.close();}
}
