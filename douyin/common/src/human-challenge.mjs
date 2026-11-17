// Read visible challenge instructions only. Never operate or solve a challenge.
export async function inspectHumanChallenge(page,platform){
 const platformHost=platform==='抖音'?'douyin.com':'xiaohongshu.com';
 const allowed=host=>host===platformHost||host.endsWith('.'+platformHost)
  ||platform==='抖音'&&['rmc.bytedance.com','verify.zijieapi.com','verify.snssdk.com'].includes(host);
 const candidates=[];
 for(const frame of page.frames()){
  let u;try{u=new URL(frame.url());}catch{continue;}
  if(u.protocol!=='https:'||!allowed(u.hostname))continue;
  try{
   if(frame!==page.mainFrame()){
    const element=await frame.frameElement();
    try{if(!await element.isVisible())continue;}finally{await element.dispose();}
   }
   const result=await frame.evaluate(()=>{
    const visible=n=>{const r=n.getBoundingClientRect();if(r.width<=0||r.height<=0)return false;
     for(let p=n;p;p=p.parentElement){const s=getComputedStyle(p);if(s.display==='none'||s.visibility==='hidden'||Number(s.opacity)<.05||p.getAttribute('aria-hidden')==='true')return false;}return true;};
    const content='section.note-item,.note-item,[data-note-id],.search-result-card,[data-e2e="search-result"],.note-container,#noteContainer,[data-e2e="feed-active-video"],[data-e2e="video-desc"],[data-e2e="comment-list"]';
    const roots=[...document.querySelectorAll('#captcha_container,[class*="secsdk-captcha"],[id*="captcha-verify"],[class*="captcha-verify"]')].filter(n=>visible(n)&&!n.closest(content));
    const scope=roots.length?roots:[document.body];
    const labels=scope.flatMap(r=>[...r.querySelectorAll('div,span,p,button,h1,h2,h3,label')])
     .filter(n=>n.childElementCount===0&&visible(n)&&!n.closest(content)).map(n=>(n.textContent||'').trim());
    const detected=[];
    if(labels.some(t=>/拖动.{0,12}(?:滑块|拼图)|滑动.{0,8}滑块|向右滑动.{0,8}验证|按住滑块/.test(t)))detected.push({type:'slider',evidence:'visible_slider_instruction'});
    if(labels.some(t=>/(?:旋转|转动).{0,16}(?:图片|图形|正向|方向)/.test(t)))detected.push({type:'rotation',evidence:'visible_rotation_instruction'});
    if(labels.some(t=>/(?:依次|按顺序).{0,8}点击|点击.{0,12}(?:指定|相同|对应).{0,8}(?:文字|图案|图形|图片)/.test(t)))detected.push({type:'click',evidence:'visible_click_instruction'});
    if(detected.length>1)return {type:'unknown',evidence:'conflicting_challenge_types'};
    if(detected.length===1)return detected[0];
    if(roots.some(r=>[...r.querySelectorAll('[role="slider"],.secsdk-captcha-drag-icon,.secsdk-captcha-drag-wrapper')].some(visible)))
     return {type:'slider',evidence:'visible_challenge_slider_control'};
    return {type:'unknown',evidence:'challenge_type_unconfirmed'};
   });
   if(result.evidence==='conflicting_challenge_types')return result;
   if(result.type!=='unknown')candidates.push(result);
  }catch{/* A changing or inaccessible frame is not subtype evidence. */}
 }
 const types=new Set(candidates.map(x=>x.type));
 return types.size===1?candidates[0]:{type:'unknown',evidence:types.size?'conflicting_challenge_types':'challenge_type_unconfirmed'};
}
