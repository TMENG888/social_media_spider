import {createHash} from 'node:crypto';
import {clickCommentExpansionWithRetry,retryableCommentClick} from './comment-click-retry.mjs';

// Fingerprints stay local to this post's comment pass. Root IDs, when actually
// present in the DOM, are preferred. Never log comment text or profile URLs.
export async function replyExpansionIdentity(control,postId){
 const value=await control.evaluate(el=>{
  const row=el.closest('[data-e2e="comment-item"],[data-e2e="comment-level-1"],[data-comment-id],[data-cid]');
  const rootId=row&&['data-comment-id','data-cid','data-id'].map(k=>row.getAttribute(k)).find(v=>/^\d{15,22}$/.test(v||''));
  if(rootId)return {rootId};
  const primary=node=>{
   const copy=node.cloneNode(true);
   copy.querySelectorAll('.replyContainer,[data-e2e="comment-reply"],button,[data-e2e="comment-like"]').forEach(n=>n.remove());
   return (copy.textContent||'').replace(/\s+/g,' ').trim().slice(0,4096);
  };
  if(row){
   const text=primary(row),panel=row.closest('[data-e2e="comment-list"],[data-e2e="comment-list-container"]');
   const twins=panel?[...panel.querySelectorAll('[data-e2e="comment-item"],[data-e2e="comment-level-1"]')].filter(n=>primary(n)===text):[row];
   return {primary:text,duplicateIndex:Math.max(0,twins.indexOf(row))};
  }
  const parent=el.closest('button')?.parentElement||el.parentElement||el;
  const panel=el.closest('[data-e2e="comment-list"],[data-e2e="comment-list-container"]');
  return {primary:primary(parent)||String(el.textContent||'').trim(),
   contentTop:Math.round((panel?.scrollTop||0)+el.getBoundingClientRect().top-(panel?.getBoundingClientRect().top||0))};
 });
 const key=createHash('sha256').update(JSON.stringify([String(postId),value])).digest('hex');
 return {controlKey:key,rootCommentId:value.rootId||null};
}

export function createReplyExpansionSkips({postId,check,flush=async()=>{},findControls,onFailure=async()=>{},onSkip=async()=>{},
 identify=control=>replyExpansionIdentity(control,postId),click=clickCommentExpansionWithRetry}){
 const skipped=new Map();
 return {
  records:()=>[...skipped.values()].map(row=>({...row})),
  async next(){
   let selected=null;
   try{
    return await click({check,flush,onFailure,findControl:async()=>{
     for(const control of await findControls()){
      const identity=await identify(control);
      if(skipped.has(identity.controlKey))continue;
      // Re-resolve this same thread on every retry, even after DOM replacement.
      if(selected&&identity.controlKey!==selected.controlKey)continue;
      selected=identity;return control;
     }
     return null;
    }});
   }catch(error){
    // Only a fully exhausted, explicitly retryable UI click can be skipped.
    // Login/security/lease/stop/programming errors retain their original path.
    if(!selected||error?.commentClickRetry?.exhausted!==true||!retryableCommentClick(error))throw error;
    await check();await flush();
    const record={...selected,reason:'comment_expansion_retry_exhausted',
     attempts:error.commentClickRetry.attempts.length,at:new Date().toISOString()};
    skipped.set(record.controlKey,record);
    try{await onSkip(record);}catch{/* Diagnostics cannot turn a local skip into a worker failure. */}
    return false;
   }
  }
 };
}
