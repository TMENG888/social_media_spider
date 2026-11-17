// Read-only observations: never click, scroll, reload, or change task outcomes.
export function inspectClickPage({noteId=''}) {
  const visible=el=>{
    if(!el)return false;
    const r=el.getBoundingClientRect();if(r.width<=0||r.height<=0)return false;
    for(let n=el;n;n=n.parentElement){const s=getComputedStyle(n);
      if(s.display==='none'||s.visibility==='hidden'||Number(s.opacity)===0||n.getAttribute('aria-hidden')==='true')return false;
    }
    return true;
  };
  const summarize=el=>el?{tag:el.tagName,classes:typeof el.className==='string'?el.className.slice(0,160):null}:null;
  const root=[...document.querySelectorAll('#noteContainer,.note-container')].find(visible);
  const currentId=location.pathname.match(/\/(?:explore|search_result)\/([a-z0-9]+)/i)?.[1]||null;
  const urlMatches=!!noteId&&currentId===noteId;
  const text=selector=>(root?.querySelector(selector)?.textContent||'').trim();
  const candidates=[...document.querySelectorAll('a[href]')].filter(el=>{
    try{return new URL(el.getAttribute('href'),location.href).pathname.match(/\/(?:explore|search_result)\/([a-z0-9]+)/i)?.[1]===noteId;}catch{return false;}
  }).slice(-8).map(el=>{
    const r=el.getBoundingClientRect(),x=r.x+r.width/2,y=r.y+r.height/2;
    const inViewport=x>=0&&x<innerWidth&&y>=0&&y<innerHeight;
    const hit=inViewport?document.elementFromPoint(x,y):null;
    return {visible:visible(el),inViewport,disabled:!!el.disabled||el.getAttribute('aria-disabled')==='true'||!!el.closest('[inert]'),
      obscured:!!hit&&hit!==el&&!el.contains(hit),hit:summarize(hit),rect:{x:r.x,y:r.y,width:r.width,height:r.height}};
  });
  const images=root?[...root.querySelectorAll('img')]:[];
  return {state:root?(urlMatches?'target_url_detail_present':'other_or_unconfirmed_detail_present'):'detail_not_visible',
    readyState:document.readyState,visibilityState:document.visibilityState,hasFocus:document.hasFocus(),
    currentNoteId:currentId,expectedNoteId:noteId,urlMatches,detailVisible:!!root,
    title:text('#detail-title,h1.title').slice(0,160),bodyChars:text('#detail-desc,.desc').length,
    dateText:text('.bottom-container .date,.note-content .date').slice(0,80),
    commentNodes:root?.querySelectorAll('.comment-item').length||0,
    images:{mounted:images.length,loaded:images.filter(i=>i.complete&&i.naturalWidth>0).length},
    loadingVisible:[...document.querySelectorAll('[aria-busy="true"],.loading,.skeleton,[class*="loading-spinner"]')].some(visible),
    loginVisible:[...document.querySelectorAll('.login-container,[class*="login-modal"]')].some(visible),
    verificationFrameVisible:[...document.querySelectorAll('iframe#nocaptcha-container,iframe[src*="rc-verifycenter"]')].some(visible),
    candidates};
}

export async function traceDetailClick(diagnostics,details,click) {
  // Diagnostic failures must never turn a successful click into collection failure.
  const observe=async(stage,extra={})=>{try{await diagnostics?.observeDetail(stage,{...details,...extra});}catch{}};
  await observe('detail_click_before');
  const started=Date.now();
  try{
    await click();
  }catch(error){
    await observe('detail_click_failed',{elapsedMs:Date.now()-started,errorName:String(error?.name||'Error'),
      error:String(error?.message||error).split('\n')[0]});
    throw error;
  }
  await observe('detail_click_returned',{elapsedMs:Date.now()-started});
}
