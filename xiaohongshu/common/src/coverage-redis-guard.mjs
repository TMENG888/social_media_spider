// Shared by leased completion and terminal-only policy revalidation. The caller
// defines `result`; this guard performs no writes, including on invalid evidence.
export const COVERAGE_REDIS_GUARD=`
if type(result)=='table' and result.acceptedBy=='article_comment_target' then
 local t=result.articleCommentTarget
 local function integer(n) return type(n)=='number' and n>=0 and n==math.floor(n) end
 local function sha(s) return type(s)=='string' and #s==64 and string.match(s,'^[a-f0-9]+$') end
 if type(t)~='table' or t.policy~='xhs-200-articles-comments-20261114-v1' or t.ok~=true
  or t.threshold~=200 or t.count~=200 or t.platform~='小红书' or t.dbReadbackVerified~=true
  or type(t.keyword)~='string' or #t.keyword==0 or t.keyword~=result.keyword
  or type(t.projectName)~='string' or #t.projectName==0 or t.projectName~=result.projectName
  or not integer(t.year) or t.cutoff~=tostring(t.year)..'-01-01'
  or not integer(t.eligibleCount) or t.eligibleCount<200 or not integer(t.commentCount)
  or type(t.articles)~='table' or #t.articles~=200 or not sha(t.articlesDigest)
  or type(t.checkedAt)~='string' or #t.checkedAt==0 or result.collectComments~=true or result.importExitCode~=0 then
  return redis.error_reply('ARTICLE_COMMENT_TARGET_UNVERIFIED')
 end
 local seen={}
 local total=0
 for _,a in ipairs(t.articles) do
  if type(a)~='table' or type(a.noteId)~='string' or #a.noteId==0 or seen[a.noteId]
   or not integer(a.commentCount) or (a.commentCount==0 and a.zeroCommentsObserved~=true)
   or not sha(a.commentsDigest) then return redis.error_reply('ARTICLE_COMMENT_PROOF_INVALID') end
  seen[a.noteId]=true
  total=total+a.commentCount
 end
 if total~=t.commentCount then return redis.error_reply('ARTICLE_COMMENT_COUNT_INVALID') end
else
local c=type(result)=='table' and result.coverage
if type(c)~='table' or c.policy~='20261015-scoped-usable-db-80-v3' or (c.scopePolicy~='20261015-target-year-relevant-v2' and c.scopePolicy~='20261114-target-year-no-lexical-filter-v1') or c.ok~=true
 or c.scanComplete~=true or c.dbReadbackVerified~=true
 or type(c.numerator)~='number' or type(c.denominator)~='number'
 or c.numerator<0 or c.denominator<0 or c.numerator>c.denominator
 or c.numerator~=math.floor(c.numerator) or c.denominator~=math.floor(c.denominator)
 or 5*c.numerator<4*c.denominator
 or (c.denominator==0 and c.emptyScope~=true) then
 return redis.error_reply('USABLE_DB_COVERAGE_UNVERIFIED')
end
local function count(value) return type(value)=='number' and value>=0 and value==math.floor(value) end
if not count(c.discoveredUniqueCount) or not count(c.excludedWithDateEvidence) or not count(c.excludedWithScopeEvidence)
 or c.discoveredUniqueCount~=c.denominator+c.excludedWithDateEvidence+c.excludedWithScopeEvidence
 or type(c.scopeExclusions)~='table' or #c.scopeExclusions~=c.excludedWithScopeEvidence
 or type(c.scopeExclusionsDigest)~='string' or #c.scopeExclusionsDigest~=64 then
 return redis.error_reply('USABLE_DB_SCOPE_EVIDENCE_UNVERIFIED')
end
local excluded={}
for _,proof in ipairs(c.scopeExclusions) do
 if type(proof)~='table' or type(proof.noteId)~='string' or #proof.noteId==0 or excluded[proof.noteId]
  or type(proof.evidenceDigest)~='string' or #proof.evidenceDigest~=64 then
  return redis.error_reply('USABLE_DB_SCOPE_EVIDENCE_UNVERIFIED')
 end
 excluded[proof.noteId]=true
end
end
`;
