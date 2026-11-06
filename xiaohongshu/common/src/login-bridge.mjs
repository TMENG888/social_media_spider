// Runs only inside the existing interactive login recovery process.
import fs from 'node:fs/promises';
import {createSmsLogin} from './sms-login.mjs';
import path from 'node:path';
import os from 'node:os';
import {observeAccountNickname} from './account-nickname.mjs';
import {randomUUID,createHash} from 'node:crypto';
import {inspectPlatformAccess} from './recovery-platform-access.mjs';

const sha=b=>createHash('sha256').update(b).digest('hex');
const delay=ms=>new Promise(r=>setTimeout(r,ms));
const uuid=/^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
async function json(file){return JSON.parse((await fs.readFile(file,'utf8')).replace(/^\uFEFF/,''));}
async function atomic(file,value){const tmp=file+'.'+process.pid+'.tmp';await fs.writeFile(tmp,JSON.stringify(value));await fs.rename(tmp,file);}
export function validateCommand(c,s,now=Date.now()){
 if(!c||!uuid.test(c.commandId||'')||c.sessionId!==s.sessionId||c.machine!==s.machine||c.platform!==s.platform||c.workerId!==s.workerId)throw new Error('TARGET_OR_SESSION_MISMATCH');
 if(!['refresh','screenshot','status','submit_sms','request_sms'].includes(c.action))throw new Error('ACTION_NOT_ALLOWED');
 if(!Number.isFinite(c.issuedAt)||!Number.isFinite(c.expiresAt)||c.issuedAt>now+5000||now-c.issuedAt>60000||c.expiresAt<=now||c.expiresAt-c.issuedAt>60000||c.expiresAt<=c.issuedAt)throw new Error('COMMAND_EXPIRED');
}
export async function startLoginBridge({common,worker,context,page,platform,incidentId,assertAllowed}){
 let config;try{config=await json(path.join(common,'login-bridge.json'));}catch(e){if(e.code==='ENOENT')return null;throw e;}
 if(config.enabled!==true)return null;
 if(typeof config.machine!=='string'||!/^work0[1-4]$/.test(config.machine))throw new Error('BRIDGE_MACHINE_CONFIG_REQUIRED');
 const root=path.join(worker,'.state','login-bridge');await fs.mkdir(root,{recursive:true});
 let supervisor=null;
 try{const v=await json(path.join(worker,'.state','monitor-supervisor.json')),age=Date.now()-Date.parse(v.updatedAt);if(Number.isInteger(v.supervisorPid)&&age>=-5000&&age<45000){process.kill(v.supervisorPid,0);supervisor={pid:v.supervisorPid,sessionId:v.sessionId};}}catch{}
 const s={schema:1,sessionId:randomUUID(),machine:config.machine,hostname:os.hostname(),platform,workerId:path.basename(worker),incidentId:incidentId||null,pid:process.pid,supervisor,createdAt:Date.now(),updatedAt:Date.now(),phase:'opening',generation:0,image:null,ack:null};
 const smsLogin=createSmsLogin({page,platform,session:s,assertAllowed});
 let busy=false,closed=false,timer,lastRefresh=0,lastOpen=0,lastCapture=0,seen=new Set();
 const accountObserver=observeAccountNickname({context,stateRoot:path.join(worker,'.state'),platform});
 const persist=async()=>{s.account=await accountObserver.snapshot();s.updatedAt=Date.now();await atomic(path.join(root,'session.json'),s);};
 const targetAllowed=()=>{const u=new URL(page.url());return u.protocol==='https:'&&(platform==='小红书'?/(^|\.)xiaohongshu\.com$/i:/(^|\.)douyin\.com$/i).test(u.hostname);};
 async function check(){await assertAllowed();if(page.isClosed()||!targetAllowed())throw new Error('PAGE_UNAVAILABLE');return inspectPlatformAccess(page,platform,{retryNavigation:false});}
 async function qr(){
  async function eligible(el){
   if(!await el.isVisible())return false;
   const box=await el.boundingBox();if(!box||box.width<80||box.height<80||box.width>600||box.height>600||Math.abs(box.width/box.height-1)>.18)return false;
   return el.evaluate(n=>n.tagName!=='IMG'||(n.complete&&n.naturalWidth>=80));
  }
  const loc=page.locator('img[class*="qrcode" i],canvas[class*="qrcode" i],canvas[class*="qr-code" i],img[class*="qr-code" i],img[class*="qr_code" i],img[alt*="二维码"],img[alt*="扫码"],[class*="qrcode" i] img,[class*="qrcode" i] canvas,[class*="qr-code" i] img,[class*="qr-code" i] canvas,[class*="qrCode"] img,[class*="qrCode"] canvas,#qrcode img,#qrcode canvas');
  for(let i=0;i<Math.min(await loc.count(),30);i++)if(await eligible(loc.nth(i)))return loc.nth(i);
  if(platform==='抖音'){
   // Douyin's login QR is an inline image with a generated CSS class.
   // Bind to the visible scan-login section, never to arbitrary page images.
   const headings=page.getByText('扫码登录',{exact:true});
   for(let i=0;i<Math.min(await headings.count(),10);i++){
    const heading=headings.nth(i);if(!await heading.isVisible())continue;
    let region=heading;
    for(let depth=0;depth<5;depth++){
     region=region.locator('xpath=..');const bounds=await region.boundingBox();
     if(!bounds||bounds.width>1100||bounds.height>1000)break;
     const images=region.locator('img[src^="data:image/"],canvas');const matches=[];
     for(let n=0;n<Math.min(await images.count(),20);n++)if(await eligible(images.nth(n)))matches.push(images.nth(n));
     if(matches.length===1)return matches[0];
     if(matches.length>1)break;
    }
   }
  }
  return null;
 }
 async function expired(){return page.getByText(/二维码已失效|二维码已过期|二维码过期|点击刷新二维码|刷新二维码|重新获取二维码/).first().isVisible().catch(()=>false);}
 async function scanPending(){
  const labels=page.getByText(/扫码成功|扫描成功|已扫码|请在手机(?:上|端)?确认|请打开手机确认|等待手机确认|正在登录|登录中/);
  for(let i=0;i<Math.min(await labels.count(),20);i++)if(await labels.nth(i).isVisible().catch(()=>false))return true;
  return false;
 }
 async function capture(){
  const access=await check();
  if(access.evidence==='sms_identity_verification'){const sms=await smsLogin.observe();s.image=null;s.phase=sms?.phase||'sms_manual';s.sms=sms?.sms||null;s.smsReason=sms?.reason||null;s.smsRequest=sms?.request||null;return false;}
  if(s.sms){smsLogin.clear();s.sms=null;}
  if(['security','captcha','gateway'].includes(access.kind)){s.phase='manual_'+access.kind;s.image=null;return false;}
  if(access.kind!=='login'||await scanPending()){s.phase='verifying';s.image=null;return false;}
  if(await expired()){s.phase='qr_expired';s.image=null;return false;}
  let el=await qr();
  if(!el&&Date.now()-lastOpen>60000){
   lastOpen=Date.now();
   for(const text of ['扫码登录','登录']){const button=page.getByText(text,{exact:true}).first();if(await button.isVisible().catch(()=>false)){await button.click({timeout:2000});await delay(800);el=await qr();if(el)break;}}
  }
  if(!el){s.phase='qr_unavailable';s.image=null;return false;}
  const bytes=await el.screenshot({type:'png',timeout:5000,animations:'disabled'}),hash=sha(bytes);
  if(await scanPending()){s.phase='verifying';s.image=null;return false;}
  // Screenshot the code only, never the desktop, cookies or storage.
  if(s.image?.sha256!==hash){
   s.generation++;const filename=`qr-${s.sessionId}-${s.generation}.png`;
   await fs.writeFile(path.join(root,filename),bytes);
   s.image={filename,sha256:hash,capturedAt:Date.now()};s.lastQrHash=hash;
   // Only files from this module, older than 24 h, are eligible for cleanup.
   for(const name of await fs.readdir(root)){if(/^qr-[0-9a-f-]+-\d+\.png$/.test(name)&&name!==filename){const f=path.join(root,name);if(Date.now()-(await fs.stat(f)).mtimeMs>86400000)await fs.unlink(f).catch(()=>{});}}
  }
  s.phase='waiting_scan';return true;
 }
 async function command(c){
  validateCommand(c,s);if(seen.has(c.commandId))return;seen.add(c.commandId);
  try{
   if(c.action==='request_sms'){
    const access=await check();if(access.evidence!=='sms_identity_verification')throw Error('SMS_PAGE_REQUIRED');
    const sms=await smsLogin.requestFresh();s.phase=sms.phase;s.sms=sms.sms;s.smsRequest=sms.request;s.smsReason=null;s.image=null;
   }else if(c.action==='submit_sms'){
    const access=await check();if(access.evidence!=='sms_identity_verification')throw Error('SMS_PAGE_REQUIRED');
    await smsLogin.submit(c);s.phase='sms_submitted';s.image=null;
   }else if(c.action!=='status'){
    if(s.phase.startsWith('sms_')||s.phase==='waiting_sms')throw Error('SMS_VERIFICATION_IN_PROGRESS');
    if(await scanPending()){s.phase='verifying';s.image=null;throw new Error('SCAN_CONFIRMATION_PENDING');}
    const access=await check();if(access.kind!=='login')throw new Error('REFRESH_REQUIRES_LOGIN_ONLY');
    if(c.action==='refresh'){
     if(Date.now()-lastRefresh<15000)throw new Error('REFRESH_RATE_LIMIT_15_SECONDS');
     lastRefresh=Date.now();const old=s.lastQrHash;
     const refresh=page.getByText(/^(?:刷新二维码|点击刷新|点击刷新二维码|重新获取二维码|刷新|重新加载)$/).first();
     if(await refresh.isVisible().catch(()=>false))await refresh.click({timeout:2500});
     else await page.reload({waitUntil:'domcontentloaded',timeout:30000});
     let changed=false;
     for(let i=0;i<8;i++){await delay(800);if(await capture()&&s.image?.sha256!==old){changed=true;break;}}
     if(!changed)throw new Error('QR_REFRESH_NOT_CONFIRMED');
    }else if(!await capture())throw new Error('QR_NOT_AVAILABLE');
   }
   s.ack={commandId:c.commandId,ok:true,action:c.action,at:Date.now(),generation:s.generation};
  }catch(e){s.ack={commandId:c.commandId,ok:false,reason:String(e.message).split('：')[0].slice(0,90),at:Date.now()};}
 }
 async function tick(){if(busy||closed)return;busy=true;
  try{
   await assertAllowed();
   let c;try{c=await json(path.join(root,'command.json'));}catch(e){if(e.code!=='ENOENT'&&!(e instanceof SyntaxError))throw e;}
   if(c&&!seen.has(c.commandId)){try{await command(c);}catch(e){if(uuid.test(c.commandId||'')){seen.add(c.commandId);s.ack={commandId:c.commandId,ok:false,reason:e.message,at:Date.now()};}}}
   if(Date.now()-lastCapture>8000){lastCapture=Date.now();await capture();}
   delete s.error;
  }catch(e){s.phase='unavailable';s.image=null;s.error=String(e.message).split('：')[0].slice(0,90);}
  finally{await persist().catch(()=>{});busy=false;}
 }
 await persist();timer=setInterval(()=>{void tick();},2000);timer.unref();void tick();
 async function stop(phase){closed=true;clearInterval(timer);accountObserver.stop();smsLogin.clear();s.sms=null;await accountObserver.flush().catch(()=>{});for(let i=0;busy&&i<240;i++)await delay(250);if(busy)throw new Error('BRIDGE_BUSY');s.phase=phase;s.image=null;await persist();}
 return {verification:check=>{s.verification={ok:check.ok,reason:check.reason,at:Date.now()};},
  prepareClose:()=>stop('verifying'),verified:async()=>{s.phase='verified';s.verifiedAt=Date.now();await persist();},
  close:async()=>{if(!closed)await stop('cancelled');else if(s.phase!=='verified'){s.phase='cancelled';await persist();}}};
}

// Telemetry only: called after the original worker enters a real keyword task.
// It neither launches a process nor modifies any operational protection.
export async function noteTaskResumed({worker,stateRoot,keyword,evidence='original_supervisor_worker_entered_keyword'}){
 const root=path.join(worker,'.state','login-bridge');
 let s;try{s=await json(path.join(root,'session.json'));}catch(e){if(e.code==='ENOENT')return;throw e;}
 if(s.phase!=='verified'||!s.supervisor||s.supervisor.pid!==process.ppid||s.hostname!==os.hostname()||!Number.isFinite(s.verifiedAt)||Date.now()<s.verifiedAt||Date.now()-s.verifiedAt>86400000)return;
 if(s.platform==='抖音'&&evidence!=='original_supervisor_content_imported')return;
 const v=await json(path.join(worker,'.state','monitor-supervisor.json'));
 const age=Date.now()-Date.parse(v.updatedAt);
 // The supervisor file records phase boundaries, not a periodic heartbeat.
 // Content import can finish minutes after entering the collecting phase.
 if(v.sessionId!==s.supervisor.sessionId||v.supervisorPid!==process.ppid||!(age>=-5000&&age<=86400000))return;
 try{process.kill(process.ppid,0);}catch{return;}
 const lock=await json(path.join(stateRoot,'worker.lock'));if(lock.pid!==process.pid)return;
 for(const name of ['supervisor.stop','stop.requested']){try{await fs.access(path.join(stateRoot,name));return;}catch(e){if(e.code!=='ENOENT')throw e;}}
 try{const previous=await json(path.join(root,'resume.json'));if(previous.sessionId===s.sessionId)return;}catch(e){if(e.code!=='ENOENT')throw e;}
 await atomic(path.join(root,'resume.json'),{schema:1,sessionId:s.sessionId,workerId:s.workerId,platform:s.platform,machine:s.machine,
  supervisor:s.supervisor,workerPid:process.pid,keyword,at:Date.now(),evidence});
}
