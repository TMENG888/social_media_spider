import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import {randomUUID,publicEncrypt,constants} from 'node:crypto';
import {chromium} from 'playwright';
import path from 'node:path';
import {createSmsLogin,smsLabel} from './src/sms-login.mjs';
const temp=path.join(process.env.LOGIN_TEST_TEMP||'E:/Codex/temp/login-sms-tests',String(Date.now()));await fs.mkdir(temp,{recursive:true});
const browser=await chromium.launch({...(process.env.LOGIN_TEST_CHROME?{executablePath:process.env.LOGIN_TEST_CHROME}:{}),headless:true,args:['--disk-cache-dir='+temp+'/cache']});
let passed=0;
async function setup({body={data:{error_code:0},message:'success'},status=200,auto=false,countdown=false,network=true,duplicate=false,face=true,outgoing=true}={}){
 const context=await browser.newContext();const page=await context.newPage();let clock=Date.now(),hits=0;
 const api='https://sso.douyin.com/passport/web/send_code/';
 await page.route(api,r=>{hits++;return r.fulfill({status,contentType:'application/json',body:typeof body==='string'?body:JSON.stringify(body)});});
 const trigger=network?`fetch('${api}',{method:'POST'}).then(()=>{window.responded=true})`:'window.responded=true';
 const html=`<meta charset="utf-8"><section style="width:700px;height:500px"><div id="choices" ${auto?'':'hidden'}><h2>身份验证</h2>${face?"<div>手机刷脸验证</div>":""}<button onclick="document.querySelector('#choices').hidden=true;document.querySelector('#form').hidden=false;window.clicks++;${trigger}">接收短信验证码</button>${outgoing?"<div>发送短信验证</div>":""}</div><div id="form" ${auto?'hidden':''}><h2>接收短信验证码</h2><p>短信已发送至绑定手机</p>${duplicate?'<p>短信已发送至绑定手机</p>':''}<input autocomplete="one-time-code" placeholder="请输入验证码"><button id="send" ${countdown?'disabled':''} onclick="window.clicks++;${trigger}">${countdown?'59秒后重新获取':'重新发送'}</button><button id="verify" onclick="window.submitted++">验证</button></div></section><script>window.responded=false;window.clicks=0;window.submitted=0</script>`;
 await page.route('https://www.douyin.com/search/test',r=>r.fulfill({contentType:'text/html; charset=utf-8',body:html}));
 await page.goto('https://www.douyin.com/search/test');let allowed=true;
 const session={sessionId:randomUUID(),machine:'work01',platform:'抖音',workerId:'worker-03'};
 const sms=createSmsLogin({page,platform:'抖音',session,now:()=>clock,assertAllowed:async()=>{if(!allowed)throw Error('OPERATOR_CANCELLED');}});
 return {page,context,sms,session,hits:()=>hits,advance:n=>{clock+=n;},allow:x=>{allowed=x;},close:async()=>{sms.clear();await context.close();}};
}
async function result(x){await x.page.waitForFunction(()=>window.responded);let state;for(let i=0;i<12;i++){await new Promise(r=>setTimeout(r,50));state=await x.sms.observe();if(state?.request)return state;}return state;}
try{
 const x=await setup({duplicate:true});assert.equal((await x.sms.observe()).phase,'sms_requesting');let st=await result(x);
 assert.equal(st.phase,'waiting_sms');assert.equal(st.request.accepted,true);assert.equal(x.hits(),1);passed++;
 for(let i=0;i<5;i++)await x.sms.observe();assert.equal(await x.page.evaluate(()=>clicks),1);passed++;
 assert.deepEqual(Object.keys(st.request).sort(),['accepted','host','httpStatus','method','observedAt','path','platformCode','requestedAt'].sort());passed++;
 const code=String(Math.floor(Math.random()*900000)+100000),cmd={challengeId:st.sms.challengeId};
 cmd.ciphertext=publicEncrypt({key:st.sms.publicKey,padding:constants.RSA_PKCS1_OAEP_PADDING,oaepHash:'sha256',oaepLabel:smsLabel(x.session,cmd.challengeId)},Buffer.from(code)).toString('base64');
 await assert.rejects(x.sms.submit({...cmd,challengeId:randomUUID()}),/CHALLENGE/);passed++;
 const wrong=publicEncrypt({key:st.sms.publicKey,padding:constants.RSA_PKCS1_OAEP_PADDING,oaepHash:'sha256',oaepLabel:smsLabel({...x.session,machine:'work02'},cmd.challengeId)},Buffer.from(code)).toString('base64');
 await assert.rejects(x.sms.submit({...cmd,ciphertext:wrong}),/DECRYPT/);passed++;
 x.allow(false);await assert.rejects(x.sms.submit(cmd),/CANCELLED/);x.allow(true);passed++;
 await x.sms.submit(cmd);assert.equal(await x.page.locator('input').inputValue(),code);assert.equal(await x.page.evaluate(()=>submitted),1);passed++;
 await assert.rejects(x.sms.submit(cmd),/PENDING/);passed++;
 await assert.rejects(x.sms.requestFresh(),/RATE_LIMIT/);passed++;
 x.advance(61000);await x.sms.requestFresh();st=await result(x);assert.notEqual(st.sms.challengeId,cmd.challengeId);assert.equal(x.hits(),2);await assert.rejects(x.sms.submit(cmd),/CHALLENGE/);passed++;
 await x.close();
 for(const options of [{body:{data:{error_code:7},message:'success'}},{status:500},{body:'not json'},{body:{unexpected:true}},{body:{code:''}},{body:{code:0,data:{error_code:9}}}]){
  const x=await setup(options);await x.sms.observe();const r=await result(x);assert.equal(r.phase,'sms_send_failed');assert.equal(r.sms,null);for(let i=0;i<3;i++)await x.sms.observe();assert.equal(x.hits(),1);passed++;await x.close();
 }
 {const x=await setup({network:false});await x.sms.observe();x.advance(16000);const r=await x.sms.observe();assert.equal(r.phase,'sms_send_unconfirmed');assert.equal(r.sms,null);assert.equal(await x.page.evaluate(()=>clicks),1);passed++;await x.close();}
 {const x=await setup({countdown:true});assert.equal((await x.sms.observe()).phase,'sms_send_unconfirmed');assert.equal(x.hits(),0);assert.equal(await x.page.evaluate(()=>clicks),0);passed++;await x.close();}
 {const x=await setup({auto:true});assert.equal((await x.sms.observe()).phase,'sms_opening');assert.equal((await result(x)).phase,'waiting_sms');assert.equal(await x.page.evaluate(()=>clicks),1);passed++;await x.close();}
 {const x=await setup({auto:true,network:false});await x.sms.observe();await result(x);x.advance(16000);assert.equal((await x.sms.observe()).phase,'sms_send_unconfirmed');assert.equal(await x.page.evaluate(()=>clicks),1);passed++;await x.close();}

 {const x=await setup({auto:true,face:false});assert.equal((await x.sms.observe()).phase,'sms_opening');const st=await result(x);assert.equal(st.phase,'waiting_sms');assert.equal(st.request.accepted,true);for(let i=0;i<5;i++)await x.sms.observe();assert.equal(await x.page.evaluate(()=>clicks),1);assert.equal(x.hits(),1);passed++;await x.close();}
 {const x=await setup({auto:true,face:false,outgoing:false});assert.equal(await x.sms.observe(),null);assert.equal(x.hits(),0);passed++;await x.close();}
}finally{await browser.close();}
const report={passed,realBrowser:true,syntheticOnly:true,staticTextInsufficient:true,businessResponseRequired:true,oneClickPerRequest:true,encryptedTargetBinding:true};
console.log(JSON.stringify(report));
