// Evaluate against the live DOM on each call. Mounted cards need not intersect
// the viewport, but their actual scroll ancestor must. Never scroll a comment
// sidebar, a search-suggestion dropdown, or an unrelated page behind a modal.
export function searchScrollDom({advance=false}={}){
 const visible=el=>{
  const r=el.getBoundingClientRect(),style=getComputedStyle(el);
  return el.getClientRects().length>0&&style.display!=='none'&&style.visibility!=='hidden'
   &&Number(style.opacity)!==0&&r.width>0&&r.height>0;
 };
 const forbidden='.search-result-card [data-e2e="comment-list"],.search-result-card [data-e2e="comment-list-container"],[data-e2e="modal-video-container"]';
 if([...document.querySelectorAll('[data-e2e="modal-video-container"]')].some(visible))return {available:false,reason:'detail_modal_open'};
 // Match visibleCards' identity rules; a descendant player is not required
 // for image cards, nor sufficient when it belongs to comments/nested cards.
 const blocked='[data-e2e="comment-list"],[data-e2e="comment-list-container"],[data-e2e="modal-video-container"],nav,aside';
 const valid=id=>/^\d{15,22}$/.test(id||'');
 const cards=[...document.querySelectorAll('.search-result-card')].filter(card=>{
  if(!visible(card)||card.closest(blocked))return false;
  const own=node=>node.closest('.search-result-card')===card&&!node.closest(blocked);
  const ids=[...new Set([card,...card.querySelectorAll('[data-e2e-vid]')].filter(own).map(el=>el.getAttribute('data-e2e-vid')).filter(valid))];
  if(!ids.length){
   for(const link of [...card.querySelectorAll('a[href]')].filter(own)){
    if(!visible(link))continue;
    try{
     const url=new URL(link.href);if(!['douyin.com','www.douyin.com'].includes(url.hostname))continue;
     const id=url.pathname.match(/^\/(?:video|note)\/(\d{15,22})\/?$/)?.[1]||url.searchParams.get('modal_id');
     if(valid(id)&&!ids.includes(id))ids.push(id);
    }catch{}
   }
  }
  return ids.length===1;
 });
 if(!cards.length)return {available:false,reason:'no_search_cards'};
 const root=document.scrollingElement,ports=new Map();
 for(const card of cards){
  let depth=0;
  for(let el=card.parentElement;el;el=el.parentElement){
   if(el===root)break;
   depth++;
   if(el.matches(forbidden)||el.closest('[data-e2e="modal-video-container"]'))continue;
   const r=el.getBoundingClientRect();
   if(visible(el)&&r.bottom>0&&r.top<innerHeight&&r.right>0&&r.left<innerWidth
    &&/(auto|scroll|overlay)/.test(getComputedStyle(el).overflowY)&&el.scrollHeight>el.clientHeight+1){
     const old=ports.get(el)||{count:0,depth};ports.set(el,{count:old.count+1,depth:Math.min(old.depth,depth)});
    }
  }
  if(root){const old=ports.get(root)||{count:0,depth:1e6};ports.set(root,{...old,count:old.count+1});}
 }
 const candidates=[...ports].sort((a,b)=>b[1].count-a[1].count||a[1].depth-b[1].depth).map(([el])=>el);
 let target=candidates[0];
 if(!target)return {available:false,reason:'no_search_scrollport'};
 let beforeTop=target.scrollTop,afterTop=beforeTop;
 const fallbackAttempts=[];
 if(advance){
  const attempts=[...new Set([...candidates.slice(0,7),root].filter(Boolean))];
  for(const candidate of attempts){
   const before=candidate.scrollTop;
   candidate.scrollBy({top:Math.max(80,Math.min(750,candidate.clientHeight*.8)),behavior:'instant'});
   const after=candidate.scrollTop;
   fallbackAttempts.push({tag:candidate.tagName,root:candidate===root,beforeTop:before,afterTop:after});
   // BODY can expose a scroll range while scrolling is actually delegated to
   // the viewport. Fall back only for this contradictory inert state; a real
   // results port at its bottom remains authoritative, not a reason to scroll
   // an unrelated outer page. All candidates are ancestors of search cards.
   if(after>before+1||candidate.scrollHeight-candidate.clientHeight-before<=2){
    target=candidate;beforeTop=before;afterTop=after;break;
   }
   if(candidate===target){beforeTop=before;afterTop=after;}
  }
 }
 const rect=target===root?{left:0,top:0,right:innerWidth,bottom:innerHeight}:target.getBoundingClientRect();
 const left=Math.max(0,rect.left),right=Math.min(innerWidth,rect.right),top=Math.max(0,rect.top),bottom=Math.min(innerHeight,rect.bottom);
 if(right-left<2||bottom-top<2)return {available:false,reason:'search_scrollport_offscreen'};
 return {available:true,scrollport:{tag:target.tagName,id:target.id||null,e2e:target.getAttribute('data-e2e'),root:target===root},
  beforeTop,afterTop,height:target.scrollHeight,viewport:target.clientHeight,movedForward:afterTop>beforeTop+1,
  atBottom:target.scrollHeight-target.clientHeight-afterTop<=2,cardCount:cards.length,
  ...(fallbackAttempts.length>1?{inertAncestorFallback:true,scrollAttempts:fallbackAttempts}:{}),
  point:{x:Math.max(left+1,right-24),y:top+(bottom-top)*.75}};
}

// No-growth is only stagnation if the real search scrollport stopped advancing.
// A repeated bounce to the same offset cannot extend a retry indefinitely.
export function searchScrollProgress(previous={},snapshot={}){
 const identity=JSON.stringify(snapshot.scrollport??null);
 const highWater=Number(previous.highWaters?.[identity]??(previous.identity===identity?previous.highWater:snapshot.beforeTop)??0);
 const progressed=snapshot.available===true&&snapshot.movedForward===true&&snapshot.afterTop>highWater+1;
 const nextHighWater=Math.max(highWater,Number(snapshot.afterTop||0));
 return {identity,highWater:nextHighWater,highWaters:{...previous.highWaters,[identity]:nextHighWater},progressed};
}
