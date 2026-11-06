// Explicit, human-authorized SMS login only. Never handles sliders or face checks.
import {generateKeyPairSync,privateDecrypt,constants,randomUUID} from 'node:crypto';

const visible=async l=>l.isVisible().catch(()=>false);
async function unique(l){const found=[];for(let i=0;i<Math.min(await l.count(),30);i++)if(await visible(l.nth(i)))found.push(l.nth(i));return found.length===1?found[0]:null;}
async function anyVisible(l){for(let i=0;i<Math.min(await l.count(),30);i++)if(await visible(l.nth(i)))return true;return false;}
const sendText=/^(获取验证码|发送验证码|获取短信验证码|发送短信验证码|接收验证码|发送|重新发送|重新获取)$/;
const submitText=/^(确认|验证|确认验证|提交|完成|下一步|登录)$/;
async function submitButton(region){return await unique(region.getByRole('button',{name:submitText})) || await unique(region.getByText(submitText,{exact:true}));}
export function smsLabel(s,c){return Buffer.from([s.sessionId,s.machine,s.platform,s.workerId,c].join('|'));}
export function createSmsLogin({page,platform,session,assertAllowed,now=Date.now}){
 let challenge=null,key=null,selected=false,requested=false,attempts=0,submittedAt=0,armedAt=0,lastRequestAt=0,receipt=null,sendClickAttempted=false,selectionAt=0;
 const requests=new WeakMap();let disposed=false;
 const matches=url=>{try{const u=new URL(url);return u.protocol==='https:'&&/(^|\.)douyin\.com$/i.test(u.hostname)&&/send[_-]?(?:sms[_-]?)?(?:code|otp)|(?:sms|otp).*send|send.*(?:sms|otp)/i.test(u.pathname);}catch{return false;}};
 const onRequest=r=>{if(armedAt&&now()-armedAt<15000&&matches(r.url())&&['GET','POST'].includes(r.method()))requests.set(r,now());};
 const onResponse=async response=>{
  const r=response.request(),at=requests.get(r);if(!at||at<armedAt||disposed)return;
  const u=new URL(r.url()),value={observedAt:now(),requestedAt:at,host:u.hostname,path:u.pathname,method:r.method(),httpStatus:response.status(),accepted:false};
  try{
   const text=await response.text();if(text.length>65536)throw Error('OVERSIZED_SMS_RESPONSE');const data=JSON.parse(text);
   const codes=[data.error_code,data.status_code,data.code,data.data?.error_code,data.data?.status_code,data.data?.code].filter(v=>v!==null&&v!==undefined).map(v=>typeof v==='number'?v:typeof v==='string'&&/^-?\d+$/.test(v)?Number(v):NaN);
   value.platformCode=codes.find(v=>v!==0)??codes[0]??null;
   value.accepted=response.status()>=200&&response.status()<300&&codes.every(v=>Number.isFinite(v)&&v===0)&&(codes.length>0||data.message==='success');
  }catch{value.reason='PLATFORM_RESPONSE_UNCONFIRMED';}
  if(!disposed&&armedAt&&at>=armedAt)receipt=value;
 };
 if(platform==='抖音'){page.on('request',onRequest);page.on('response',onResponse);}
 const publish=()=>challenge?{...challenge,attempts}:null;
 function clear(){key=null;challenge=null;disposed=true;page.off('request',onRequest);page.off('response',onResponse);}
 function outcome(phase,extra={}){return {phase,sms:publish(),request:receipt?{...receipt}:null,...extra};}
 async function locate(){
  if(platform!=='抖音'||page.isClosed())return null;
  const u=new URL(page.url());if(u.protocol!=='https:'||!/(^|\.)douyin\.com$/i.test(u.hostname))return null;
  const results=[];
  for(const frame of page.frames()){
   let url;try{url=new URL(frame.url());}catch{continue;}
   if(url.protocol!=='https:'||!/(^|\.)douyin\.com$/i.test(url.hostname))continue;
   const heading=await unique(frame.getByText(/^(身份验证|短信验证|短信验证码验证|手机验证)$/)) || await unique(frame.getByText('接收短信验证码',{exact:true}));
   if(!heading)continue;
   let region=heading,choice=null,entry=null;
   for(let d=0;d<7;d++){
    region=region.locator('xpath=..');if(await region.count()!==1)break;const b=await region.boundingBox({timeout:2500});
    if(!b||b.width>1400||b.height>1200)break;
    // Reject unrelated captchas, including an embedded verification frame.
    if(await region.locator('iframe[src*="verify"],#captcha_container,[class*="slider" i]').count())continue;
    const option=await unique(region.getByText('接收短信验证码',{exact:true}));
    const input=await unique(region.locator('input[autocomplete="one-time-code"],input[placeholder*="验证码"],input[aria-label*="验证码"]'));
    // The current title is also “接收短信验证码”. Continue to the actual
    // form; a title is never a clickable receive-SMS option.
    if(input&&await submitButton(region)){entry={frame,region,option:null,input};break;}
    // Douyin can show only the two SMS methods. Face verification is optional;
    // bind the receive option to this visible identity-method selector instead.
    if(option&&await anyVisible(region.getByText('身份验证',{exact:true}))
       &&await anyVisible(region.getByText('发送短信验证',{exact:true})))choice={frame,region,option,input:null};
   }
   if(entry||choice)results.push(entry||choice);
  }
  return results.length===1?results[0]:null;
 }
 async function observe(){
  await assertAllowed();let dom=await locate();
  if(!dom){if(challenge){clear();return {phase:'sms_submitted'};}return null;}
  if(!dom.input){
   if(selected)return {phase:'sms_manual',reason:'SMS_INPUT_NOT_FOUND'};
   selected=true;selectionAt=now();armedAt=selectionAt;lastRequestAt=selectionAt;await dom.option.click({timeout:2500});return outcome('sms_opening');
  }
  if(!requested){
   // Set before clicking: a timeout must never cause another SMS to be sent.
   if(receipt?.accepted){requested=true;lastRequestAt=receipt.requestedAt;}
   else if(receipt)return outcome('sms_send_failed',{reason:'PLATFORM_REJECTED_OR_UNCONFIRMED'});
   else if(sendClickAttempted)return outcome(now()-armedAt<15000?'sms_requesting':'sms_send_unconfirmed',{reason:'NO_FRESH_PLATFORM_SEND_RECEIPT'});
   else{
    // Selecting this method can itself send a code. Wait for its response;
    // never click “resend” in the same polling round or during a countdown.
    if(selectionAt&&now()-selectionAt<15000)return outcome('sms_requesting');
    if(await anyVisible(dom.region.getByText(/^\d+\s*(?:秒|s|S)|(?:重新发送|重新获取).*\d/)))return outcome('sms_send_unconfirmed',{reason:'COUNTDOWN_WITHOUT_PLATFORM_RECEIPT'});
    // A static “短信已发送” label or a resend control is not a send receipt.
    const send=await unique(dom.region.getByText(sendText));
    if(!send||!await send.isEnabled())return outcome('sms_send_unconfirmed',{reason:'SEND_CONTROL_NOT_READY'});
    if(selectionAt&&/^重新/.test((await send.innerText()).trim()))return outcome('sms_send_unconfirmed',{reason:'SELECTION_SEND_RESULT_UNKNOWN_USE_EXPLICIT_RESEND'});
    sendClickAttempted=true;armedAt=now();lastRequestAt=armedAt;
    await send.click({timeout:2500});return outcome('sms_requesting');
   }
  }
  if(!challenge){
   // Request is confirmed by the page before advertising a code challenge.
   if(!receipt?.accepted)return outcome('sms_send_unconfirmed',{reason:'NO_FRESH_PLATFORM_SEND_RECEIPT'});
   const pair=generateKeyPairSync('rsa',{modulusLength:2048,publicKeyEncoding:{type:'spki',format:'pem'}});
   key=pair.privateKey;challenge={challengeId:randomUUID(),publicKey:pair.publicKey,issuedAt:now(),expiresAt:now()+300000};
  }
  if(now()>=challenge.expiresAt||attempts>=3){key=null;return outcome('sms_expired');}
  if(submittedAt&&now()-submittedAt<15000)return outcome('sms_submitted');
  const error=await unique(dom.region.getByText(/验证码错误|验证码不正确|验证码已过期|验证码失效/));
  return outcome(error?'sms_rejected':'waiting_sms');
 }
 async function requestFresh(){
  await assertAllowed();if(disposed)throw Error('SMS_SESSION_CLOSED');
  const dom=await locate();if(!dom?.input)throw Error('SMS_INPUT_NOT_VISIBLE');
  if(lastRequestAt&&now()-lastRequestAt<60000)throw Error('SMS_REQUEST_RATE_LIMIT_60_SECONDS');
  if(submittedAt&&now()-submittedAt<15000)throw Error('SMS_SUBMISSION_PENDING');
  const send=await unique(dom.region.getByText(sendText));if(!send||!await send.isEnabled())throw Error('SMS_SEND_CONTROL_NOT_READY');
  key=null;challenge=null;receipt=null;attempts=0;submittedAt=0;requested=false;
  sendClickAttempted=true;armedAt=now();lastRequestAt=armedAt;
  await send.click({timeout:2500});return outcome('sms_requesting');
 }
 async function submit(c){
  await assertAllowed();
  if(!challenge||!key||now()>=challenge.expiresAt||c.challengeId!==challenge.challengeId||attempts>=3)throw Error('SMS_CHALLENGE_EXPIRED_OR_CHANGED');
  if(submittedAt&&now()-submittedAt<15000)throw Error('SMS_SUBMISSION_PENDING');
  const dom=await locate();if(!dom?.input)throw Error('SMS_INPUT_NOT_VISIBLE');
  const button=await submitButton(dom.region);
  if(!button)throw Error('SMS_SUBMIT_BUTTON_NOT_UNIQUE');
  if(typeof c.ciphertext!=='string'||!/^[A-Za-z0-9+/]{340,344}={0,2}$/.test(c.ciphertext))throw Error('SMS_CIPHERTEXT_INVALID');
  let bytes;
  try{bytes=privateDecrypt({key,padding:constants.RSA_PKCS1_OAEP_PADDING,oaepHash:'sha256',oaepLabel:smsLabel(session,c.challengeId)},Buffer.from(c.ciphertext,'base64'));}
  catch{throw Error('SMS_DECRYPT_REJECTED');}
  try{
   if(!/^\d{4,8}$/.test(bytes.toString('ascii')))throw Error('SMS_CODE_FORMAT');
   await assertAllowed();attempts++;submittedAt=now();
   // Deliberately use evaluate rather than Playwright fill: operation errors and
   // call logs must not include the code argument. No tracing/screenshots here.
   await dom.input.evaluate((n,value)=>{const set=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set;set.call(n,value);n.dispatchEvent(new Event('input',{bubbles:true}));n.dispatchEvent(new Event('change',{bubbles:true}));},bytes.toString('ascii'));
   if(!await button.isEnabled())throw Error('SMS_SUBMIT_DISABLED');
   await button.click({timeout:2500});
  }catch{throw Error('SMS_SUBMIT_NOT_CONFIRMED');}
  finally{bytes?.fill(0);}
 }
 return {observe,submit,requestFresh,clear};
}
