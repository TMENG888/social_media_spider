import test from 'node:test';import assert from 'node:assert/strict';
import {recoverableContentGap,boundedRecoveryDisposition} from './content-recovery.mjs';
import {YearBoundary,searchExhaustionEvidence,verifiedAnnualSearchEnd} from './collection-policy.mjs';
import {readFileSync} from 'node:fs';
test('content-only gaps continue but safety, DB and programming errors stop',()=>{
 for(const message of ['DETAIL_DATA_NOT_OBSERVED：missing','COMMENTS_INCOMPLETE：missing','SEARCH_CARD_NOT_VISIBLE：missing'])assert.equal(recoverableContentGap(new Error(message)),true);
 for(const message of ['STOP_LOGIN_REQUIRED','STOP_PLATFORM_RESTRICTION','STOP_SEARCH_CONTEXT_LOST','TypeError','MYSQL_IMPORT_FAILED'])assert.equal(recoverableContentGap(new Error(message)),false);
 assert.equal(recoverableContentGap(Object.assign(new Error('COMMENTS_INCOMPLETE'),{importPending:true})),false);
 assert.deepEqual(boundedRecoveryDisposition(new Set(['old'])).unlocatedCandidates,['old']);
});
test('verified pagination can end with detail gaps, gaps retained for coverage',()=>{
 const input={keyword:'k',after:1,sortConfirmed:true,pages:[{keyword:'k',at:2,latest:true,offset:0,hasMore:false,noteIds:['missing']}],uiEnd:{visible:true,text:'end'}};
 const e=searchExhaustionEvidence(input);assert.equal(e.confirmed,true);assert.deepEqual(e.gaps,['missing']);
 assert.equal(searchExhaustionEvidence({...input,uiEnd:{visible:false}}).confirmed,false);
 assert.equal(searchExhaustionEvidence({...input,pages:[{...input.pages[0],hasMore:true}]}).confirmed,false);
});

test('eight old posts cannot end an annual search before an interleaved current-year post',()=>{
 const boundary=new YearBoundary(2026,8);
 for(let i=0;i<8;i++)boundary.observe(`old-${i}`,'2025-12-31');
 assert.equal(boundary.reached,true);
 assert.equal(verifiedAnnualSearchEnd({keyword:'k',sortConfirmed:true,stopReason:'year_boundary',oldDateWindowObserved:true}),false);
 boundary.observe('current','2026-01-01');assert.equal(boundary.reached,false);
 const source=readFileSync(new URL('./collector.mjs',import.meta.url),'utf8');
 assert.doesNotMatch(source,/stopReason\s*=\s*['"]year_boundary['"]/);
 assert.equal(source.match(/oldDateWindowObserved=true/g)?.length,3);
 assert.match(source,/scanComplete:verifiedAnnualSearchEnd\(summary\)/);
});

test('annual endpoint requires repeated matching current-keyword pagination proof',()=>{
 const evidence=searchExhaustionEvidence({keyword:'k',after:1,sortConfirmed:true,pages:[{keyword:'k',at:2,latest:true,offset:0,hasMore:false,noteIds:[]}],uiEnd:{visible:true,text:'没有更多了'}});
 const summary={keyword:'k',sortConfirmed:true,stopReason:'search_exhausted',searchExhaustion:{...evidence,stableChecks:2}};
 assert.equal(verifiedAnnualSearchEnd(summary),true);
 for(const patch of [{confirmed:false},{keyword:'other'},{sortConfirmed:false},{hasMore:true},{stableChecks:1},{stableChecks:2.5},{reason:'year_boundary'}]){
  assert.equal(verifiedAnnualSearchEnd({...summary,searchExhaustion:{...summary.searchExhaustion,...patch}}),false);
 }
 assert.equal(verifiedAnnualSearchEnd({...summary,sortConfirmed:false}),false);
 assert.equal(verifiedAnnualSearchEnd({...summary,stopReason:'sample_limit'}),false);
 assert.equal(verifiedAnnualSearchEnd({...summary,searchExhaustion:undefined}),false);
});
test('date exclusions are not reported as saved recovery successes',()=>{
 const source=readFileSync(new URL('./collector.mjs',import.meta.url),'utf8');
 assert.match(source,/if\(!noteError&&durable\)summary\.recoveredDetailNotes\.push/);
 assert.match(source,/else if\(!noteError&&dateExcluded\)summary\.recoveredOldNotes\.push/);
 assert.doesNotMatch(source,/if\(!noteError\)summary\.recoveredDetailNotes\.push/);
 assert.match(source,/summary\.unlocatedCandidates\?\.length\|\|0/);
});
