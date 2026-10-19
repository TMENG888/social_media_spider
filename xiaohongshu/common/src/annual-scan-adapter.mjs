import {SearchExhaustion} from './search-acceptance.mjs';
import {createHash} from 'node:crypto';

export function collectorAnnualScan(record,task){
 const summaries=record.searchSummaries||[];
 const s=summaries.length===1&&summaries[0].keyword===task.keyword?summaries[0]:null;
 const e=s?.exhaustion,origin=s?.origin,observations=e?.observations;
 let ok=s?.reason==='platform_exhausted'&&s.latestConfirmed===true&&e?.ok===true
  &&e.policy==='20261014-verified-search-end-v1'&&e.scope==='platform_current_visible_results'
  &&origin?.contextValid===true&&origin.rendered===true&&!origin.loading&&!origin.loadFailed
  &&Number.isFinite(origin.top)&&origin.top<=8&&origin.top>=0
  &&Array.isArray(observations)&&Number.isSafeInteger(e.requiredRounds)&&e.requiredRounds>=2&&e.requiredRounds<=100;
 if(ok){
  const replay=new SearchExhaustion({stableRounds:e.requiredRounds,terminalRounds:e.requiredRounds});
  let state,previous=Date.parse(origin.capturedAt);
  ok=Number.isFinite(previous)&&previous>=Date.parse(s.startedAt)&&previous<=Date.parse(s.finishedAt);
  for(const snapshot of observations){
   const stamp=Date.parse(snapshot.capturedAt);
   if(!Number.isFinite(stamp)||stamp<previous||stamp>Date.parse(s.finishedAt))ok=false;
   previous=stamp;state=replay.observe(snapshot);
  }
  ok=ok&&state?.ok===true;
 }
 return {...task,ok:Boolean(ok),policy:'20261014-verified-search-end-v1',
  startedAtTop:Boolean(ok),latestConfirmed:s?.latestConfirmed===true,
  startedAt:s?.startedAt,finishedAt:s?.finishedAt,scope:'platform_current_visible_results',
  observations:Array.isArray(observations)?observations.length:0,
  rawEvidenceDigest:s?createHash('sha256').update(JSON.stringify(s)).digest('hex'):null};
}
