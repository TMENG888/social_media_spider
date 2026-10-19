import {douyinAnnualScan} from './keyword-annual-acceptance.mjs';

export function collectorAnnualScan(record,task){
 return douyinAnnualScan({status:record.error?'failed':'completed',fatalError:record.error,
  currentKeyword:record.keyword,startedAt:record.startedAt,finishedAt:record.finishedAt,tasks:[record]},task);
}
