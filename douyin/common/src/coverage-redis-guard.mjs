// Shared by leased completion and terminal-only policy revalidation. The caller
// defines `result`; this guard performs no writes, including on invalid evidence.
export const COVERAGE_REDIS_GUARD=`
local c=type(result)=='table' and result.coverage
if type(c)~='table' or c.policy~='20261015-scoped-usable-db-80-v3' or c.scopePolicy~='20261015-target-year-relevant-v2' or c.ok~=true
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
`;
