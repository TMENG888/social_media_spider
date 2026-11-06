import {riskVolumeEvidence} from './risk-volume-completion.mjs';
export const RISK_RETRY_POLICY='security-retry-local-increment-20261105-v1';
export function riskRetryIncrementEvidence(record={}){
 const safety=riskVolumeEvidence(record);if(!safety)return null;
 const observation=record.retryObservation;
 if(!observation||observation.keyword!==record.keyword||observation.runId!==record.runId
  ||!record.runId||observation.freshSearch!==true)return null;
 const before=observation.before?.retainedArticleIds,after=observation.after?.retainedArticleIds;
 if(!Array.isArray(before)||!Array.isArray(after))return null;
 const valid=ids=>ids.every(id=>typeof id==='string'&&id.trim()===id&&id.length>0);
 if(!valid(before)||!valid(after))return null;
 const previous=new Set(before),current=new Set(after);
 // Count new article identities, never scanned candidates, comments, ASR
 // updates, cumulative exports, or SQL updates to an existing article.
 const newIds=[...current].filter(id=>!previous.has(id));
 if(!newIds.length)return null;
 return {...safety,policy:RISK_RETRY_POLICY,runId:record.runId,keyword:record.keyword,
  baselinePosts:previous.size,retainedPosts:current.size,newLocalPosts:newIds.length,
  newArticleIds:newIds,quantityAccepted:false,qualityVerified:false};
}
