"""Explicit, one-time correction of a retained, already-consumed original child.

Never invoked by scheduler startup. Default is read-only preview; apply requires
the exact policy and original message/task/fingerprint. It restores that same
stream ID, not a new task, and archives prior evidence before a bounded attempt.
"""
import hashlib
import json
import re
from datetime import datetime
from subtitle_review import checkpoint_repair_reason

POLICY='20261015-exact-original-delivery-correction-v1'

APPLY="""
local cp=redis.call('HGET',KEYS[2],ARGV[4])
local budget=redis.call('HGET',KEYS[3],ARGV[5]) or ''
local prior=redis.call('HGET',KEYS[4],ARGV[5])
if prior then return redis.error_reply('REPAIR_ALREADY_RECORDED') end
if cp~=ARGV[6] or budget~=ARGV[7] then return redis.error_reply('REPAIR_EVIDENCE_CHANGED') end
if redis.call('SISMEMBER',KEYS[5],ARGV[5])~=1 then return redis.error_reply('REPAIR_ORIGINAL_SEED_MISSING') end
local original=redis.call('XRANGE',KEYS[1],ARGV[2],ARGV[2],'COUNT',1)
if #original~=1 or original[1][1]~=ARGV[2] then return redis.error_reply('REPAIR_ORIGINAL_MESSAGE_MISSING') end
local fields={};for i=1,#original[1][2],2 do fields[original[1][2][i]]=original[1][2][i+1] end
if fields.payload~=ARGV[8] or fields.retry_id~=ARGV[5] then return redis.error_reply('REPAIR_ORIGINAL_PAYLOAD_CHANGED') end
local pending=redis.call('XPENDING',KEYS[1],ARGV[1],ARGV[2],ARGV[2],1)
if #pending~=0 then return redis.error_reply('REPAIR_ORIGINAL_STILL_PENDING') end
local cursor=nil
for _,g in ipairs(redis.call('XINFO','GROUPS',KEYS[1])) do
 local values={};for i=1,#g,2 do values[g[i]]=g[i+1] end
 if values.name==ARGV[1] then cursor=values['last-delivered-id'] end
end
local function number_le(a,b)
 a=a:gsub('^0+','');b=b:gsub('^0+','')
 return #a<#b or (#a==#b and a<=b)
end
local function id_le(a,b)
 local am,as=a:match('^(%d+)%-(%d+)$');local bm,bs=b:match('^(%d+)%-(%d+)$')
 return am and bm and ((am==bm and number_le(as,bs)) or (am~=bm and number_le(am,bm)))
end
if not cursor or not id_le(ARGV[2],cursor) then return redis.error_reply('REPAIR_ORIGINAL_NOT_CONSUMED') end
-- Type, retained entry, exact bytes, cursor and absent pending were all checked
-- before the first mutation. Checkpoint and seed stay byte-for-byte unchanged.
redis.call('HSET',KEYS[4],ARGV[5],ARGV[9])
redis.call('HSET',KEYS[3],ARGV[5],ARGV[10])
local restored=redis.call('XCLAIM',KEYS[1],ARGV[1],ARGV[3],0,ARGV[2],'FORCE','JUSTID')
if #restored~=1 or restored[1]~=ARGV[2] then return redis.error_reply('REPAIR_RESTORE_UNCONFIRMED_READBACK_REQUIRED') end
return restored[1]
"""

def _object(raw):
    value=json.loads(raw)
    if not isinstance(value,dict): raise ValueError('REPAIR_INVALID_OBJECT')
    return value

def restore_original_delivery(q,args,item,message_id,*,apply=False,policy=None):
    if policy!=POLICY: raise ValueError('REPAIR_EXPLICIT_POLICY_REQUIRED')
    if not re.fullmatch(r'\d+-\d+',str(message_id)): raise ValueError('REPAIR_EXACT_MESSAGE_REQUIRED')
    parent=item.get('source_task_id') or item.get('task_id');fp=item.get('fingerprint')
    if not parent or not fp or not item.get('keyword') or not item.get('topic') or not str(args.consumer).strip():
        raise ValueError('REPAIR_EXACT_IDENTITY_REQUIRED')
    retry_id=hashlib.sha256(f'{parent}|{fp}'.encode()).hexdigest()
    stream=args.retry_stream;group=args.retry_group
    keys=[stream,args.prefix+':video-state:'+q.safe_token(parent),args.prefix+':video-retry-budget',
          args.prefix+':original-delivery-correction-history',args.retry_seeded_key]
    def read(*parts): return q.redis_command(args.redis_url,args.redis_password,*parts)
    cp_raw=read('HGET',keys[1],fp)
    cp=_object(cp_raw)
    reason=checkpoint_repair_reason(cp,collect_comments=q.coverage_collect_comments(item))
    if cp.get('status') not in {'completed','no_content','not_applicable'} or not reason:
        raise ValueError('REPAIR_KNOWN_BAD_TERMINAL_REQUIRED')
    if read('HGET',keys[3],retry_id): raise ValueError('REPAIR_ALREADY_RECORDED')
    budget_raw=read('HGET',keys[2],retry_id) or ''
    budget=_object(budget_raw) if budget_raw else None
    if budget and (budget.get('state')!='accepted' or budget.get('messageId')!=message_id):
        raise ValueError('REPAIR_PRIOR_ACCEPTED_BUDGET_REQUIRED')
    if not read('SISMEMBER',keys[4],retry_id): raise ValueError('REPAIR_ORIGINAL_SEED_MISSING')
    rows=read('XRANGE',stream,message_id,message_id,'COUNT',1) or []
    if len(rows)!=1 or rows[0][0]!=message_id: raise ValueError('REPAIR_ORIGINAL_MESSAGE_MISSING')
    fields=q.fields_to_dict(rows[0][1]);payload_raw=fields.get('payload');payload=_object(payload_raw)
    if fields.get('retry_id')!=retry_id or payload.get('source_task_id')!=parent or payload.get('fingerprint')!=fp or payload.get('keyword')!=item['keyword'] or payload.get('topic')!=item['topic']:
        raise ValueError('REPAIR_ORIGINAL_IDENTITY_MISMATCH')
    if read('XPENDING',stream,group,message_id,message_id,1): raise ValueError('REPAIR_ORIGINAL_STILL_PENDING')
    groups=[q.fields_to_dict(g) for g in read('XINFO','GROUPS',stream)]
    cursor=next((g['last-delivered-id'] for g in groups if g['name']==group),None)
    if cursor is None or tuple(map(int,message_id.split('-')))>tuple(map(int,cursor.split('-'))):
        raise ValueError('REPAIR_ORIGINAL_NOT_CONSUMED')
    prior_counts=[cp.get('retry_count',0)]+([budget.get('attempts')] if budget else [])
    if any(not isinstance(n,int) or isinstance(n,bool) or n<0 for n in prior_counts):
        raise ValueError('REPAIR_ATTEMPT_HISTORY_INVALID')
    known=max(prior_counts)
    audit={'policy':POLICY,'taskId':parent,'fingerprint':fp,'keyword':item['keyword'],'topic':item['topic'],
           'messageId':message_id,'reason':reason,'previousCheckpointRaw':cp_raw,
           'previousBudgetRaw':budget_raw or None,'originalPayloadRaw':payload_raw,
           'knownAttemptsBaseline':known,'legacyAttemptsUnknown':budget is None,
           'extraAttemptLimit':1,'createdAt':datetime.now().astimezone().isoformat()}
    new_budget={**(budget or {}),'state':'pending','attempts':known,'maxAttempts':known+1,
                'messageId':message_id,'owner':args.consumer,'token':None,
                'outcome':{'ok':False,'accepted':False,'status':'correction_pending'},
                'originalDeliveryCorrection':{'policy':POLICY,
                'historyKey':keys[3],'legacyAttemptsUnknown':budget is None,'extraAttemptLimit':1}}
    preview={'policy':POLICY,'applied':False,'taskId':parent,'fingerprint':fp,'messageId':message_id,
             'repairReason':reason,'knownAttemptsBaseline':known,'legacyAttemptsUnknown':budget is None,
             'extraAttemptLimit':1,'checkpointUnchanged':True,'noNewStreamEntry':True}
    if not apply: return preview
    encoded=lambda value:json.dumps(value,ensure_ascii=False,separators=(',',':'))
    restored=read('EVAL',APPLY,len(keys),*keys,group,message_id,args.consumer,fp,retry_id,
                  cp_raw,budget_raw,payload_raw,encoded(audit),encoded(new_budget))
    if restored!=message_id: raise q.RedisError('REPAIR_RESTORE_UNCONFIRMED_READBACK_REQUIRED')
    # Do not claim success from Lua's return alone; check the exact durable
    # evidence/budget and exact original pending owner after the atomic action.
    pending=read('XPENDING',stream,group,message_id,message_id,1) or []
    if read('HGET',keys[1],fp)!=cp_raw or _object(read('HGET',keys[3],retry_id))!=audit or _object(read('HGET',keys[2],retry_id))!=new_budget or len(pending)!=1 or pending[0][1]!=args.consumer:
        raise q.RedisError('REPAIR_READBACK_UNCONFIRMED_DO_NOT_REPEAT_BLINDLY')
    return {**preview,'applied':True,'durableReadbackVerified':True}
