// Passive observation of this browser's own authenticated account only.
import fs from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
export function cleanNickname(value){
 if(typeof value!=='string')return null;
 const text=value.replace(/[\p{Cc}\p{Cf}]/gu,'').trim();
 return text&&text.length<=80&&!/^(?:登录|扫码登录|未登录|游客|guest|undefined|null)$/i.test(text)?text:null;
}
export function selfNickname(platform,url,data){
 let u;try{u=new URL(url);}catch{return null;}
 if(u.protocol!=='https:')return null;
 if(platform==='小红书'&&/(^|\.)xiaohongshu\.com$/i.test(u.hostname)&&/^\/api\/sns\/web\/v\d+\/user\/selfinfo\/?$/.test(u.pathname)
  &&data?.success===true&&(data.code==null||data.code===0))return cleanNickname(data.data?.basic_info?.nickname||data.data?.nickname);
 if(platform==='抖音'&&/(^|\.)douyin\.com$/i.test(u.hostname)&&/^\/aweme\/v1\/web\/user\/profile\/self\/?$/.test(u.pathname)
  &&data?.status_code===0)return cleanNickname(data.user?.nickname);
 return null;
}
export async function readAccountNickname(stateRoot,platform){
 try{
  const file=path.join(stateRoot,'account-nickname.json');if((await fs.stat(file)).size>4096)return null;
  const a=JSON.parse(await fs.readFile(file,'utf8'));
  if(a.schema!==1||a.hostname!==os.hostname()||a.platform!==platform||a.profile!=='browser-profile'||a.workerId!==path.basename(path.dirname(stateRoot))
    ||!cleanNickname(a.nickname)||!Number.isFinite(a.observedAt)||a.observedAt>Date.now()+5000)return null;
  return a;
 }catch{return null;}
}
export function observeAccountNickname({context,stateRoot,platform}){
 let active=true,busy=false,writing=Promise.resolve(),last=null;
 const file=path.join(stateRoot,'account-nickname.json');
 async function remember(nickname,source){
  nickname=cleanNickname(nickname);if(!active||!nickname)return;
  const a={schema:1,nickname,hostname:os.hostname(),platform,workerId:path.basename(path.dirname(stateRoot)),profile:'browser-profile',source,observedAt:Date.now()};
  // Serialize writes; never persist response bodies, tokens or cookies.
  writing=writing.catch(()=>{}).then(async()=>{const tmp=file+'.'+process.pid+'.tmp';await fs.mkdir(stateRoot,{recursive:true});await fs.writeFile(tmp,JSON.stringify(a));await fs.rename(tmp,file);last=a;});
  await writing;
 }
 const response=async res=>{
  try{
   const u=new URL(res.url());
   const allowed=platform==='小红书'?/(^|\.)xiaohongshu\.com$/i.test(u.hostname)&&/^\/api\/sns\/web\/v\d+\/user\/selfinfo\/?$/.test(u.pathname)
     :/(^|\.)douyin\.com$/i.test(u.hostname)&&/^\/aweme\/v1\/web\/user\/profile\/self\/?$/.test(u.pathname);
   if(!allowed||u.protocol!=='https:'||!res.ok())return;
   const nickname=selfNickname(platform,res.url(),await res.json());if(nickname)await remember(nickname,'authenticated_self_response');
  }catch{}
 };
 async function sample(){
  if(!active||busy)return;busy=true;
  try{
   if(platform!=='小红书')return;
   for(const page of context.pages()){
    let u;try{u=new URL(page.url());}catch{continue;}
    if(u.protocol!=='https:'||!/(^|\.)xiaohongshu\.com$/i.test(u.hostname))continue;
    const nickname=await page.evaluate(()=>{
     const unwrap=v=>v&&typeof v==='object'?('value' in v?v.value:('_value' in v?v._value:v)):v;
     const user=unwrap(window.__INITIAL_STATE__?.user);
     if((unwrap(user?.isLogin)??unwrap(user?.isLoggedIn))!==true)return null;
     const self=unwrap(user?.userInfo)||unwrap(user?.userinfo);
     return typeof self?.nickname==='string'?self.nickname:null;
    });
    if(nickname)await remember(nickname,'authenticated_current_user_state');
   }
  }catch{}finally{busy=false;}
 }
 context.on('response',response);const timer=setInterval(()=>{void sample();},15000);timer.unref();void sample();
 const stop=()=>{active=false;clearInterval(timer);context.off('response',response);};context.once('close',stop);
 return {snapshot:async()=>last||readAccountNickname(stateRoot,platform),sample,flush:()=>writing,stop};
}
