// Quantity acceptance must not wait for the entire subtitle backlog. Finish
// only the job already running; durable pending/dead-letter records stay true.
// Non-quantity collection keeps its existing drain/quality behavior.
export async function finalizeAsr(processor,{volumeMode=false,closeOnly=false,readStats}={}){
 if(!processor)return null;
 if(!volumeMode&&!closeOnly)return processor.drain();
 await processor.close();
 return {...readStats(),runtimeUnavailable:Boolean(processor.haltedReason),
  runtimeError:processor.haltedReason||null,drainConfirmed:false,
  quantityFinalization:volumeMode?'current_job_only_pending_retained':null};
}
