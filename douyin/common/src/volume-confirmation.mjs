// Collector-local counts are provisional. Only the final fenced SQL/Redis
// confirmation can promote a keyword to quantity-completed.
export function volumeQueueConfirmed(confirmation) {
 return confirmation?.status==='completed'&&confirmation?.acceptedByVolume===true;
}

export function keywordQueueConfirmed(confirmation) {
 return volumeQueueConfirmed(confirmation)||confirmation?.status==='completed'&&(confirmation?.acceptedBySearchExhaustion===true||confirmation?.acceptedByAnnual===true||confirmation?.acceptedByExhaustion===true||confirmation?.acceptedByResetOnce===true);
}

export function reconcileVolumeCompletion(record,confirmation) {
 const confirmed=keywordQueueConfirmed(confirmation);
 return {...record,status:confirmed?'completed':'incomplete',accepted:confirmed,
  redisConfirmed:confirmed,redisDisposition:String(confirmation?.status||'unconfirmed'),
  quantityAccepted:volumeQueueConfirmed(confirmation),annualLowVolumeAccepted:confirmed&&confirmation?.acceptedByAnnual===true,
  retryExhaustedCompletion:confirmed&&confirmation?.acceptedByExhaustion===true,
  searchExhaustionCompleted:confirmed&&confirmation?.acceptedBySearchExhaustion===true,
  resetOnceCompletion:confirmed&&confirmation?.acceptedByResetOnce===true,
  ...(confirmation?.acceptedByResetOnce?{collectionSucceeded:confirmation.collectionSucceeded===true,
   dataImported:confirmation.dataImported===true,businessCompleted:true,collectionError:record.collectionError||record.error||null}:{}),
  pendingImport:confirmation?.pendingImport===true,
  error:confirmed?null:record.error||'VOLUME_FINAL_CONFIRMATION_NOT_COMPLETED'};
}
