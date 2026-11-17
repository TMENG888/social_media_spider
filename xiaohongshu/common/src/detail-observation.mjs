import {createHash} from 'node:crypto';
export const DETAIL_OBSERVATION_VERSION='xhs-rendered-detail-20261110-v1';

// Passed to Playwright: no references to module-level values here.
export function inspectDetailInPage({noteId='',gate=false,securityPattern='',unavailablePattern=''}={}){
 const visible=n=>{if(!n)return false;const b=n.getBoundingClientRect(),s=getComputedStyle(n);return b.width>0&&b.height>0&&s.display!=='none'&&s.visibility!=='hidden';};
 const actualId=location.pathname.match(/\/(?:explore|search_result)\/([0-9a-f]{24})(?:\/|$)/i)?.[1]||'';
 const roots=[...document.querySelectorAll('#noteContainer,.note-container')].filter(visible),root=roots.length===1?roots[0]:null;
 const rootId=root?.getAttribute('data-note-id')||root?.getAttribute('data-noteid')||'';
 const bound=Boolean(actualId&&(!noteId||actualId===noteId)&&(!rootId||rootId===actualId));
 const text=selector=>root?.querySelector(selector)?.textContent?.trim()||'';
 // Responsive detail layouts keep a hidden author header before the visible one.
 // Validate the visible author instead of rejecting a fully rendered note because
 // querySelector happened to return the hidden copy first.
 const author=root?[...root.querySelectorAll('.author-container a[href*="/user/profile/"],.author a[href*="/user/profile/"],a[href*="/user/profile/"]')].find(visible):null;
 const dateRaw=text('.bottom-container .date,.note-content .date');
 const images=root?[...root.querySelectorAll('.swiper-slide img,.note-slider-img img,img.note-slider-img')].filter(n=>n.complete&&n.naturalWidth>0):[];
 const video=root?.querySelector('video'),videoReady=Boolean(video&&video.readyState>=1&&(video.currentSrc||video.src||video.querySelector('source')?.src));
 const textVisible=Boolean(root&&[...root.querySelectorAll('#detail-title,#detail-desc,h1.title,.desc')].some(n=>visible(n)&&n.textContent?.trim()));
 const authorObserved=Boolean(author&&visible(author));
 const ready=Boolean(bound&&root&&authorObserved&&dateRaw&&(textVisible||images.length||videoReady));
 const snapshot={noteId:actualId,expectedNoteId:noteId||actualId,bound,detailVisible:Boolean(root),ready,authorObserved,dateRaw,
  loadedImages:images.length,videoReady,titleLength:text('#detail-title,h1.title').length,descriptionLength:text('#detail-desc,.desc').length,
  authorUrl:author?.getAttribute('href')?.split('?')[0]||null,imageUrls:images.map(n=>n.currentSrc||n.src),observedAt:new Date().toISOString()};
 if(gate){const body=document.body?.innerText||'';return ready||Boolean(securityPattern&&new RegExp(securityPattern).test(body))||Boolean(unavailablePattern&&new RegExp(unavailablePattern).test(body));}
 return snapshot;
}

export async function waitForObservedDetail(page,{noteId='',timeout=45000,assertSafe,securityPattern='',unavailablePattern=''}={}){
 await assertSafe(page);
 await page.waitForFunction(inspectDetailInPage,{noteId,gate:true,securityPattern,unavailablePattern},{timeout});
 await assertSafe(page);
 const observation=await page.evaluate(inspectDetailInPage,{noteId});
 if(!observation.ready)throw new Error('DETAIL_NOT_RENDERED：当前帖子主体、作者、日期或媒体尚未加载');
 return {version:DETAIL_OBSERVATION_VERSION,...observation};
}

export function textlessReview({keyword,noteId,publishedAt,scopeEvidence,scopeAssessment,observation}){
 if(scopeAssessment?.status!=='unobserved'||!observation?.ready||!observation.bound||observation.noteId!==noteId
  ||observation.expectedNoteId!==noteId||!/^\d{4}-\d{2}-\d{2}$/.test(String(publishedAt||'').slice(0,10)))return null;
 if(/[\p{L}\p{N}]/u.test(String(scopeEvidence?.title||'')+String(scopeEvidence?.body||'')))return null;
 return {textlessReview:{version:DETAIL_OBSERVATION_VERSION,keyword,noteId,reason:'rendered_without_scope_text',detail:observation},
  publishedAt,scopeEvidence,scopeAssessment,comments:[]};
}

export function isTextlessReview(note,keyword){
 const p=note?.result?.textlessReview;
 return note?.status==='textless_review'&&p?.version===DETAIL_OBSERVATION_VERSION&&p.keyword===keyword
  &&p.noteId===note.noteId&&p.detail?.ready===true&&p.detail.bound===true&&p.detail.noteId===note.noteId;
}

export function retainTextlessReview(db,keyword,note,result){
 if(!isTextlessReview({status:'textless_review',noteId:note.noteId,result},keyword)||result.post)throw new Error('TEXTLESS_REVIEW_EVIDENCE_INVALID');
 const stamp=new Date().toISOString();db.exec('BEGIN IMMEDIATE');
 try{
  const prior=db.prepare('SELECT * FROM candidate WHERE keyword=? AND note_id=?').get(keyword,note.noteId);
  if(!prior)throw new Error('TEXTLESS_REVIEW_CANDIDATE_MISSING');
  if(prior.result_json){
   const priorScope=db.prepare('SELECT * FROM scope_audit WHERE keyword=? AND note_id=?').get(keyword,note.noteId)||null;
   const oldJson=JSON.stringify(prior),scopeJson=JSON.stringify(priorScope),hash=createHash('sha256').update(JSON.stringify([oldJson,scopeJson])).digest('hex');
   db.prepare('INSERT OR IGNORE INTO scope_evidence_history VALUES(?,?,?,?,?,?)').run(keyword,note.noteId,hash,oldJson,scopeJson,stamp);
  }
  db.prepare("UPDATE candidate SET status='textless_review',attempts=attempts+1,result_json=?,last_error='DETAIL_RENDERED_WITHOUT_SCOPE_TEXT',updated_at=? WHERE keyword=? AND note_id=?")
   .run(JSON.stringify(result),stamp,keyword,note.noteId);
  db.prepare(`INSERT INTO scope_audit(keyword,note_id,assessment_json,checked_at) VALUES(?,?,?,?)
   ON CONFLICT(keyword,note_id) DO UPDATE SET assessment_json=excluded.assessment_json,checked_at=excluded.checked_at`)
   .run(keyword,note.noteId,JSON.stringify(result.scopeAssessment),stamp);
  db.exec('COMMIT');
 }catch(error){db.exec('ROLLBACK');throw error;}
}
