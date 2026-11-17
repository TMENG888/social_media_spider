// Read-only recognition of a real SMS form. Never reads input values or codes.
export function smsPlatformHost(platform,host){
 return (platform==='小红书'?/(^|\.)xiaohongshu\.com$/i:platform==='抖音'?/(^|\.)douyin\.com$/i:/$a/).test(host);
}
export async function inspectSmsVerification(page,platform){
 if(page.isClosed())return null;
 let top;try{top=new URL(page.url());}catch{return null;}
 if(top.protocol!=='https:'||!smsPlatformHost(platform,top.hostname))return null;
 const matches=[];
 for(const frame of page.frames()){
  let u;try{u=new URL(frame.url());}catch{continue;}
  if(u.protocol!=='https:'||!smsPlatformHost(platform,u.hostname))continue;
  const result=await frame.evaluate(()=>{
   const shown=n=>{const r=n.getBoundingClientRect();if(!r.width||!r.height)return false;for(let p=n;p;p=p.parentElement){const s=getComputedStyle(p);if(s.display==='none'||s.visibility==='hidden'||Number(s.opacity)<.05||p.getAttribute('aria-hidden')==='true')return false;}return true;};
   const headings=[...document.querySelectorAll('h1,h2,h3,div,span,p')].filter(n=>n.childElementCount===0&&shown(n)&&/^(短信验证码验证|短信验证|手机验证)$/.test(n.textContent.trim()));
   const found=[];
   for(const heading of headings){
    let region=heading;
    for(let depth=0;depth<7;depth++){
     region=region.parentElement;if(!region||region===document.body||region===document.documentElement)break;
     const b=region.getBoundingClientRect();if(b.width>1400||b.height>1200)break;
     const text=region.innerText||'';
     if(/拖动.*滑块|拖动.*拼图|旋转.*图片|完成.*滑块|手机刷脸|人脸识别/.test(text)||[...region.querySelectorAll('iframe[src*="verify"],#captcha_container,[class*="slider" i]')].some(shown))continue;
     const inputs=[...region.querySelectorAll('input[autocomplete="one-time-code"],input[placeholder*="验证码"],input[aria-label*="验证码"]')].filter(shown);
     const buttons=[...region.querySelectorAll('button,[role="button"],div,span')].filter(n=>n.childElementCount===0&&shown(n)&&/^(确认|验证|确认验证|提交|完成|下一步|登录)$/.test(n.textContent.trim()));
     if(inputs.length!==1||buttons.length!==1)continue;
     const phone=text.match(/1\d{2}[*•●xX]{3,}(\d{2,4})/);
     found.push({sent:!!phone&&/验证码已发送至|短信已发送至|已发送验证码至/.test(text),willSend:!!phone&&/验证码将发送至|短信将发送至/.test(text),phoneTail:phone?.[1]||null});break;
    }
   }
   return found.length===1?found[0]:null;
  });
  if(result)matches.push(result);
 }
 return matches.length===1?matches[0]:null;
}
