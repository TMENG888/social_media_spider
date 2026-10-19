import test from 'node:test';
import assert from 'node:assert/strict';
import {bindCurrentMedia,assertMediaProvenance,MEDIA_BINDING_VERSION,currentMediaSnapshot} from './media-provenance.mjs';
const id='6a50baaf000000002102222a',url='https://sns-video.example.invalid/current.mp4';
const snapshot=()=>({noteId:id,routeId:id,recordId:id,pageDuration:184,videoSrc:'blob:current',video:{media:{stream:{h264:[{masterUrl:url}]}}}});
test('blob video uses exact note metadata, never historical resource fallback',()=>{
 const s=snapshot();s.performanceUrls=['https://example.invalid/old.mp4'];s.otherNote={video:'https://example.invalid/old.mp4'};
 const r=bindCurrentMedia(s);assert.equal(r.url,url);assert.equal(r.binding.version,MEDIA_BINDING_VERSION);
 assert.throws(()=>assertMediaProvenance(r.binding,{noteId:id,url,duration:95.434}),/DURATION_MISMATCH/);
 assert.equal(assertMediaProvenance(r.binding,{noteId:id,url,duration:184.1}).durationVerified,true);
});
test('184 and 159 second regressions reject the old 95.434 second media',()=>{
 for(const duration of [184,159]){const s={...snapshot(),pageDuration:duration};const r=bindCurrentMedia(s);
 assert.throws(()=>assertMediaProvenance(r.binding,{noteId:id,url,duration:95.434}),/DURATION_MISMATCH/);}
});
test('stale DOM src, wrong detail identity, missing duration and broad state fail closed',()=>{
 assert.equal(bindCurrentMedia({...snapshot(),videoSrc:'https://example.invalid/previous.mp4'}).url,url);
 assert.equal(bindCurrentMedia({...snapshot(),routeId:'6acf15ba000000001b02e721'}).ok,false);
 assert.equal(bindCurrentMedia({...snapshot(),recordId:'other',videoSrc:'blob:current'}).ok,false);
 assert.equal(bindCurrentMedia({...snapshot(),recordId:'other',videoSrc:'https://example.invalid/old.mp4'}).ok,false);
 assert.equal(bindCurrentMedia({...snapshot(),pageDuration:0}).ok,false);
 assert.equal(bindCurrentMedia({...snapshot(),video:{cover:'https://example.invalid/cover.png'}}).ok,false);
});
test('same duration is insufficient without note/source identity',()=>{
 const r=bindCurrentMedia(snapshot());
 assert.throws(()=>assertMediaProvenance(r.binding,{noteId:'other',url,duration:184}),/UNVERIFIED/);
 assert.throws(()=>assertMediaProvenance(r.binding,{noteId:id,url:'https://example.invalid/other.mp4',duration:184}),/UNVERIFIED/);
});

test('browser fixture reads only the keyed current note despite old-note state and stale DOM src',async()=>{
 const {chromium}=await import('playwright');
 const browser=await chromium.launch({headless:true,...(process.env.XHS_TEST_BROWSER?{executablePath:process.env.XHS_TEST_BROWSER}:{})});
 try{
  const page=await browser.newPage();
  await page.setContent('<div id="detail" data-note-id="6a50baaf000000002102222a"><h1 class="title">current title</h1><video></video></div>');
  await page.evaluate(({id,url})=>{
   const previous='6acf15ba000000001b02e721';
   globalThis.__INITIAL_STATE__={note:{noteDetailMap:{[previous]:{note:{noteId:previous,title:'old',video:{masterUrl:'https://example.invalid/old.mp4'}}},[id]:{note:{noteId:id,title:'current title',video:{masterUrl:url}}}}}};
   const video=document.querySelector('video');Object.defineProperty(video,'duration',{value:184});
   Object.defineProperty(video,'currentSrc',{value:'https://example.invalid/old.mp4'});
  },{id,url});
  const s=await page.locator('#detail').evaluate(currentMediaSnapshot,id);
  const bound=bindCurrentMedia(s);assert.equal(bound.ok,true);assert.equal(bound.url,url);
 }finally{await browser.close();}
});
