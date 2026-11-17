import test from 'node:test';
import assert from 'node:assert/strict';
import {YearBoundary} from './collection-policy.mjs';
import {consumeSearchCandidates,verifiedYearBoundary} from './year-boundary-stop.mjs';
import {assessSearchAcceptance} from './search-acceptance.mjs';

async function scan(dates,{latest=true,annual=true,limit=3,failAt=-1}={}){
 const boundary=new YearBoundary(2026,8),progress={targetYear:2026,latestConfirmed:latest,accepted:0};
 const visited=[];let loads=0,closed=false;
 async function* source(){
  try{for(let i=0;i<dates.length;i++){loads++;yield {noteId:'note-'+i,date:dates[i]};}progress.reason='platform_exhausted';progress.exhaustion={ok:true};}
  finally{closed=true;}
 }
 let error;
 try{await consumeSearchCandidates(source(),{boundary,progress,collectAllCurrentYear:annual,maxNotesPerKeyword:limit,
  processNote:async note=>{
   visited.push(note.noteId);
   if(visited.length===failAt)throw new Error('STOP_LOGIN_REQUIRED');
   boundary.observe(note.noteId,note.date);
   if(note.date?.startsWith('2026'))progress.accepted++;
  }});}catch(e){error=e;}
 return {boundary,progress,visited,loads,closed,error};
}
const old=()=>Array(8).fill('2025-12-31');
test('eighth verified old detail closes the iterator before a ninth card or next scroll',async()=>{
 const s=await scan(['2026-11-11',...old(),'2024-01-01']);
 assert.equal(s.error,undefined);assert.equal(s.visited.length,9);assert.equal(s.loads,9);assert.equal(s.closed,true);
 assert.equal(s.progress.reason,'year_boundary');assert.equal(verifiedYearBoundary(s.progress),true);
 assert.deepEqual(assessSearchAcceptance([s.progress]),{ok:true,scope:'latest_search_through_year_boundary',reason:'verified_year_boundary'});
});
for(const middle of [null,'2026-09-09','2027-01-01','2025-02-30']){
 test('unknown/invalid/current/future date breaks the old detail streak: '+middle,async()=>{
  const dates=[...old().slice(0,7),middle,...old(),'2025-01-01'];
  const s=await scan(dates);assert.equal(s.loads,16);assert.equal(s.progress.reason,'year_boundary');
 });
}
test('re-reading one old note never supplies eight distinct observations',()=>{
 const b=new YearBoundary(2026,8);for(let i=0;i<20;i++)b.observe('same','2025-12-31');
 assert.equal(b.reached,false);assert.equal(b.recent.length,1);
});
test('seven old notes still require the search endpoint',async()=>{
 const s=await scan(old().slice(0,7));assert.equal(s.progress.yearBoundary,undefined);
 assert.equal(s.progress.reason,'platform_exhausted');assert.equal(assessSearchAcceptance([s.progress]).reason,'verified_search_endpoint');
});
test('unconfirmed latest order cannot terminate a live search by date',async()=>{
 const s=await scan([...old(),...old()],{latest:false});assert.equal(s.loads,16);
 assert.equal(s.progress.reason,'platform_exhausted');assert.equal(s.progress.yearBoundary,undefined);
});
test('login/lease/control errors propagate without a successful boundary',async()=>{
 const s=await scan(old(),{failAt:8});assert.match(s.error.message,/STOP_LOGIN_REQUIRED/);
 assert.equal(s.progress.yearBoundary,undefined);assert.equal(assessSearchAcceptance([s.progress]).ok,false);
});
test('evidence is rechecked rather than trusting a success flag',async()=>{
 const s=await scan(old());
 for(const mutate of [p=>p.latestConfirmed=false,p=>p.targetYear=2027,p=>p.yearBoundary.required=7,
  p=>p.yearBoundary.observations.pop(),p=>p.yearBoundary.observations[7].noteId='note-0',
  p=>p.yearBoundary.observations[3].date='2026-10-01',p=>p.yearBoundary.observations[3].date=null,
  p=>p.yearBoundary.source='card_date']){
  const p=structuredClone(s.progress);mutate(p);assert.equal(assessSearchAcceptance([p]).ok,false);
 }
});
test('explicit sampling keeps its original cap',async()=>{
 const s=await scan(Array(10).fill('2026-11-11'),{annual:false});
 assert.equal(s.loads,3);assert.equal(s.progress.reason,'sample_limit');
});
