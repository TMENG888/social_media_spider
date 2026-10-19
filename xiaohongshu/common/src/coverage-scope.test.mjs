import test from 'node:test';
import assert from 'node:assert/strict';
import {DatabaseSync} from 'node:sqlite';
import {existsSync} from 'node:fs';
import * as x from './coverage-gate.mjs';
import {attachScopeAudits} from './coverage-scope.mjs';
const dySource=existsSync(new URL('../../../douyin/common/src/coverage-gate.mjs',import.meta.url))
 ? '../../../douyin/common/src/' : '../../../抖音/common/src/';
const d=await import(new URL(dySource+'coverage-gate.mjs',import.meta.url));

const keyword='保利熙瑞 看房';
const note=id=>({noteId:String(id),status:'completed',publishedAt:'2026-10-01',result:{post:{文章id:String(id),文章链接:`https://example.invalid/${id}`,文章标题:'保利熙瑞户型',文章内容:'目标项目内容',项目:'fixture',内容类型:'图文'}}});
function excluded(id){
 const n=note(id);n.status='skipped_irrelevant';n.result.post.文章标题='广州天河现房';n.result.post.文章内容='广州天河其他楼盘内容';
 n.scopeAudit={keyword,noteId:String(id),checkedAt:'2026-10-15T10:00:00Z',assessment:{policy:'20261015-positive-scope-evidence-v2',status:'out_of_scope',anchors:['保利熙瑞'],matches:[],reason:'configured_other_entity_observed',exclusion:{kind:'configured_entity',entity:'广州天河',field:'title'}}};
 return n;
}
for(const [platform,gate] of [['xhs',x],['douyin',d]]){
 test(`${platform}: missing entity name is uncertain, never an exclusion or a verified positive`,()=>{
  const n=note('uncertain');n.result.post.文章标题='家人们，保利这个给我都去看';n.result.post.文章内容='西四环的保利新房，海淀南北双阳台';
  const r=gate.assessCoverage([n],{keyword,scanComplete:true,verifiedIds:[n.noteId]});
  assert.equal(r.denominator,1);assert.equal(r.numerator,0);assert.equal(r.uncertainRelevanceCount,1);assert.equal(r.ok,false);
  n.status='skipped_irrelevant';n.scopeAudit={keyword,noteId:n.noteId,checkedAt:'2026-10-15T10:00:00Z',
   assessment:{policy:'20261014-keyword-anchor-v1',status:'out_of_scope',anchors:['保利熙瑞'],matches:[],reason:'entity_anchor_not_observed'}};
  const old=gate.assessCoverage([n],{keyword,scanComplete:true});
  assert.equal(old.denominator,1);assert.equal(old.excludedWithScopeEvidence,0);assert.equal(old.ok,false);
 });
 test(`${platform}: explicit retained irrelevant evidence is separate, never numerator success`,()=>{
  const good=Array.from({length:8},(_,i)=>note(i)),unknown=note(8),dead=note(9);unknown.status='pending';dead.status='dead_letter';
  const irrelevant=Array.from({length:479},(_,i)=>excluded(100+i));
  const r=gate.assessCoverage([...good,unknown,dead,...irrelevant],{keyword,scanComplete:true,verifiedIds:good.map(n=>n.noteId)});
  assert.equal(r.policy,'20261015-scoped-usable-db-80-v3');assert.equal(r.numerator,8);assert.equal(r.denominator,10);assert.equal(r.ok,true);
  assert.equal(r.excludedWithScopeEvidence,479);assert.equal(r.excludedWithDateEvidence,0);assert.equal(r.discoveredUniqueCount,489);
  assert.equal(r.scopeExclusions.length,479);assert.equal(r.scopeExclusions[0].evidenceDigest.length,64);
  assert.equal(irrelevant[0].status,'skipped_irrelevant'); // Assessment does not mutate source records.
 });
 test(`${platform}: missing, mismatched, uncertain or contradicted exclusions stay in denominator`,()=>{
  const changes=[n=>delete n.scopeAudit,n=>n.scopeAudit.noteId='other',n=>n.scopeAudit.keyword='其他项目 看房',
   n=>n.scopeAudit.checkedAt='invalid',n=>n.scopeAudit.assessment.status='unobserved',
   n=>n.scopeAudit.assessment.anchors=['广州'],n=>n.scopeAudit.assessment.matches=[{anchor:'保利熙瑞',field:'title'}],
   n=>n.result.post.文章标题='保利·熙瑞户型',n=>n.result.post.文章id='other',
   n=>delete n.scopeAudit.assessment.exclusion,
   n=>n.scopeAudit.assessment.exclusion.entity='未观察到的项目',
   n=>n.scopeAudit.assessment.reason='entity_anchor_not_observed',
   n=>{n.result.post.文章标题='';n.result.post.文章内容='';n.result.post.文章标签='广州';}];
  for(const change of changes){const n=excluded('excluded');change(n);const r=gate.assessCoverage([n],{keyword,scanComplete:true});
   assert.equal(r.denominator,1);assert.equal(r.excludedWithScopeEvidence,0);assert.equal(r.ok,false);}
 });
 test(`${platform}: date exclusion, scope exclusion and zero-result endpoint remain distinct`,()=>{
  const old=excluded('old');old.status='skipped_old';old.publishedAt='2025-01-01';
  const foreign=excluded('foreign');
  const r=gate.assessCoverage([old,foreign],{keyword,scanComplete:true});
  assert.equal(r.denominator,0);assert.equal(r.excludedWithDateEvidence,1);assert.equal(r.excludedWithScopeEvidence,1);assert.equal(r.emptyScope,true);
  assert.equal(gate.assessCoverage([old,foreign],{keyword,scanComplete:false}).ok,false);
 });
 test(`${platform}: fresh scope-only evidence needs the keyed detail observation`,()=>{
  const n=excluded('fresh');n.result={outsideScope:true,scopeEvidence:{title:'广州天河现房',body:'广州天河其他楼盘'},publishedAt:'2026-10-01'};
  assert.equal(gate.assessCoverage([n],{keyword,scanComplete:true}).excludedWithScopeEvidence,1);
  delete n.result.outsideScope;
  assert.equal(gate.assessCoverage([n],{keyword,scanComplete:true}).denominator,1);
 });
}
test('read-only scoped audit attaches only matching keyword/identity, tolerates absent or malformed legacy audit',()=>{
 const db=new DatabaseSync(':memory:');
 try{
  const n=excluded('n');assert.equal(attachScopeAudits(db,[n],keyword)[0],n);
  db.exec('CREATE TABLE scope_audit(keyword TEXT,note_id TEXT,assessment_json TEXT,checked_at TEXT)');
  db.prepare('INSERT INTO scope_audit VALUES(?,?,?,?)').run(keyword,'n',JSON.stringify(n.scopeAudit.assessment),n.scopeAudit.checkedAt);
  const input={...n,scopeAudit:null};
  const [attached]=attachScopeAudits(db,[input],keyword);
  assert.equal(x.assessCoverage([attached],{keyword,scanComplete:true}).excludedWithScopeEvidence,1);
  assert.equal(input.scopeAudit,null);
  db.exec("UPDATE scope_audit SET assessment_json='{broken'");
  assert.equal(x.assessCoverage(attachScopeAudits(db,[input],keyword),{keyword,scanComplete:true}).denominator,1);
 }finally{db.close();}
});
