"""One-time, fenced repair of legacy infrastructure-only false completions.

Runs only after offline import recovery. Content-exhaustion, finite content
failure and explicit user completions are not candidates. No new task is added.
"""
import json

VERSION = 'channels-infra-completion-repair-20261021-v1'
LEGACY_ERRORS = {
    'Operational incident state unavailable; no inner retry.',
    'RECOLLECTION_LEASE_EXPIRED',
}

REPAIR = r'''
local id,mid,group,version=ARGV[1],ARGV[2],ARGV[3],ARGV[4]
local raw=redis.call('HGET',KEYS[1],id)
local ledger=redis.call('HGET',KEYS[2],id)
local function out(v) return cjson.encode(v) end
if raw~=ARGV[5] or ledger~=ARGV[6] then return out({status='changed_since_preview'}) end
local r=cjson.decode(raw);local s=cjson.decode(ledger)
local e=r.outcome or {}
if r.status~='completed' or r.acceptedBy~='reset_once_recollection'
 or r.collectionSucceeded~=false or r.dataImported~=true or r.pendingImport~=false
 or s.state~='completed' or s.result~=raw or s.policy~='reset-once-20261016-v1'
 or s.originalMessageId~=mid or not s.preservation or s.preservation.keyword~=ARGV[7]
 or s.infrastructureCompletionRepair
 or not (e.error=='Operational incident state unavailable; no inner retry.' or e.error=='RECOLLECTION_LEASE_EXPIRED')
 then return out({status='not_eligible'}) end
-- Probe all types and original identity before any write (Lua has no rollback).
local field=id..'|'..version
if redis.call('HGET',KEYS[3],field) then return out({status='already_repaired'}) end
if redis.call('HGET',KEYS[4],id) then return out({status='busy'}) end
local rows=redis.call('XRANGE',KEYS[5],mid,mid)
if #rows~=1 then return out({status='original_missing'}) end
local payload=nil
for i=1,#rows[1][2],2 do if rows[1][2][i]=='payload' then payload=rows[1][2][i+1] end end
local p=cjson.decode(payload or '{}')
if p.task_id~=id or p.keyword~=ARGV[7] then return out({status='original_mismatch'}) end
if #redis.call('XPENDING',KEYS[5],group,mid,mid,1)>0 then return out({status='busy'}) end
local t=redis.call('TIME');local now=tonumber(t[1])*1000+math.floor(tonumber(t[2])/1000)
redis.call('HSET',KEYS[3],field,cjson.encode({previousStatus=raw,previousLedger=ledger,at=now,version=version}))
s.infrastructureCompletionRepair={version=version,at=now,reason=e.error,previousOwner=s.owner}
s.state='armed';s.token=nil;s.owner=nil;s.result=nil;s.finishedAt=nil
redis.call('HSET',KEYS[2],id,cjson.encode(s))
redis.call('HSET',KEYS[1],id,cjson.encode({status='recollect_pending',accepted=false,
 businessCompleted=false,taskId=id,keyword=p.keyword,messageId=mid,repairVersion=version,
 previousDataPreserved=true,dataImported=true,pendingImport=false,reason='legacy_infrastructure_completion'}))
return out({status='rearmed',changed=true,version=version})
'''


def repair_legacy_completions(runtime, stopped):
    def records(key):
        values = runtime.command('HGETALL', key) or []
        return dict(zip(values[::2], values[1::2]))
    statuses = records(runtime.args.status_key)
    ledgers = records(runtime.args.prefix + ':recollection-once')
    summary = {'version': VERSION, 'rearmed': 0, 'awaitingImport': 0, 'conflicts': 0}
    for task in runtime.selected:
        if stopped():
            break
        tid = task['task_id']
        raw, ledger_raw = statuses.get(tid), ledgers.get(tid)
        try:
            r, s = json.loads(raw or '{}'), json.loads(ledger_raw or '{}')
            if (r.get('status') != 'completed' or r.get('acceptedBy') != 'reset_once_recollection'
                    or r.get('collectionSucceeded') is not False
                    or (r.get('outcome') or {}).get('error') not in LEGACY_ERRORS
                    or s.get('state') != 'completed' or s.get('result') != raw
                    or s.get('infrastructureCompletionRepair')):
                continue
        except (ValueError, TypeError, AttributeError):
            continue
        if r.get('dataImported') is not True or r.get('pendingImport') is not False:
            summary['awaitingImport'] += 1
            continue
        mid, original = runtime.messages[tid]
        if original != task:
            raise RuntimeError('INFRA_REPAIR_ORIGINAL_MISMATCH')
        result = json.loads(runtime.command('EVAL', REPAIR, 5,
            runtime.args.status_key, runtime.args.prefix + ':recollection-once',
            runtime.args.prefix + ':recollection-history', runtime.args.prefix + ':volume-lease-tokens',
            runtime.args.stream, tid, mid, runtime.args.group, VERSION, raw, ledger_raw, task['keyword']))
        summary['rearmed' if result.get('status') == 'rearmed' else 'conflicts'] += 1
        print(json.dumps({'event': 'legacy_infrastructure_completion_repair', 'taskId': tid,
            'keyword': task['keyword'], 'collectionReplayed': False, **result}, ensure_ascii=False), flush=True)
    print(json.dumps({'event': 'legacy_infrastructure_repair_summary', **summary}), flush=True)
    return summary
