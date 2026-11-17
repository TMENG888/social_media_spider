const messages={sms_code_incorrect:'短信验证码错误，请重新输入。',sms_code_expired:'短信验证码已失效，请重新获取。',qr_expired:'二维码已失效，请刷新二维码。',qr_rejected:'扫码登录未通过，请重新扫码。',login_required_again:'页面重新要求登录，尚未取得有效登录凭证。'};
export function classifyLoginFeedback(text){
 if(typeof text!=='string')return null;
 let type;
 if(/(?:短信)?验证码.{0,8}(?:已?过期|已?失效)|(?:已?过期|已?失效).{0,5}验证码/.test(text))type='sms_code_expired';
 else if(/(?:短信)?验证码.{0,8}(?:错误|不正确|有误|不匹配|无效)|(?:错误|无效)的?验证码/.test(text))type='sms_code_incorrect';
 else if(/二维码.{0,8}(?:已?过期|已?失效|无效)|(?:刷新|重新获取)二维码/.test(text))type='qr_expired';
 else if(/扫码.{0,8}(?:失败|被拒绝|已取消)|(?:登录已取消|拒绝登录)/.test(text))type='qr_rejected';
 return type?{type,message:messages[type]}:null;
}
export function loginFeedback(type,now=Date.now()){return messages[type]?{type,message:messages[type],at:now}:null;}
export async function inspectLoginFeedback(page,platform){
 const domain=platform==='小红书'?'xiaohongshu.com':platform==='抖音'?'douyin.com':null;
 if(!domain||page.isClosed())return null;
 for(const frame of page.frames()){
  let u;try{u=new URL(frame.url());}catch{continue;}
  if(u.protocol!=='https:'||!(u.hostname===domain||u.hostname.endsWith('.'+domain)))continue;
  const labels=await frame.evaluate(()=>{
   const visible=n=>{const b=n.getBoundingClientRect();if(!b.width||!b.height)return false;for(let p=n;p;p=p.parentElement){const s=getComputedStyle(p);if(s.display==='none'||s.visibility==='hidden'||Number(s.opacity)<.05||p.getAttribute('aria-hidden')==='true')return false;}return true;};
   const content='section.note-item,.note-item,[data-note-id],.note-container,#noteContainer,[data-e2e="comment-list"],[data-e2e="feed-active-video"],.search-result-card';
   return [...document.querySelectorAll('p,span,div,button,[role="alert"]')].filter(n=>n.childElementCount===0&&!n.closest(content)&&visible(n)).map(n=>(n.textContent||'').trim()).filter(t=>t.length>0&&t.length<180).slice(0,500);
  });
  for(const label of labels){const feedback=classifyLoginFeedback(label);if(feedback)return {...feedback,at:Date.now(),source:'visible_page'};}
 }
 return null;
}
