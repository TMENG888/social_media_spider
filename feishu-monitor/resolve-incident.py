"""Explicit exact-incident operator confirmation. Never removes stop files."""
import argparse
import importlib.util
import json
import sys
from pathlib import Path
spec=importlib.util.spec_from_file_location('incident_relay',Path(__file__).with_name('incident-relay.py'))
relay=importlib.util.module_from_spec(spec);spec.loader.exec_module(relay)
from operational_gate import OperationalGate, SCRIPT

def main():
    p=argparse.ArgumentParser()
    for flag in ('platform','machine','worker','incident-id'):p.add_argument('--'+flag,required=True)
    a=p.parse_args()
    target=next((s for s in relay.sources() if s[0]==a.platform),None)
    if not target:raise ValueError('Unknown platform')
    _,namespace,url,password=target
    keys=[namespace+':monitor:incidents',namespace+':monitor:outbox']
    with relay.RedisConnection(url,password,timeout=5) as c:
        gate=OperationalGate(c.command,a.worker,a.platform,machine=a.machine,keys=keys)
        state=gate.read()
        if state.get('incidentId')!=a.incident_id or state.get('status')!='manual_required':
            raise ValueError('Incident changed or not awaiting human confirmation')
        # Guard the exact incident again in Redis, not just an earlier UI read.
        guard="""
redis.call('HGET',KEYS[2],'__probe__')
local s=cjson.decode(redis.call('HGET',KEYS[1],ARGV[2]) or '{}')
if s.incidentId~=ARGV[5] or s.status~='manual_required' then return redis.error_reply('INCIDENT_CHANGED') end
"""
        if a.platform=='小红书':
            common=relay.platform_path('小红书')/'common'
            config=json.loads((common/'config.json').read_text(encoding='utf-8-sig'))
            group=config.get('rateLimitCooldown',{}).get('group','shared')
            keys.append(namespace+':rate-limit-cooldown:'+group)
            guard+="""
local other_manual=false
for _,raw in ipairs(redis.call('HVALS',KEYS[1])) do
 local ok,r=pcall(cjson.decode,raw)
 if ok and type(r)=='table' and r.field~=ARGV[2] and r.status=='manual_required' then other_manual=true end
end
local raw=redis.call('HGET',KEYS[3],'state')
if raw and not other_manual then
 local hold=cjson.decode(raw)
 if hold.workerId==s.workerId and hold.manualRequired==true then
  redis.call('HSET',KEYS[3],'operator-confirmed:'..ARGV[5],raw)
  hold.manualRequired=false;hold.untilMs=0;hold.resetBy=s.machine..'/'..s.workerId
  redis.call('HSET',KEYS[3],'state',cjson.encode(hold))
 end
end
"""
        c.command('EVAL',guard+SCRIPT,len(keys),*keys,'resolve',gate.field,'operator_confirmed',0,a.incident_id)
        print('Exact incident confirmed. Stop markers, tasks and collector processes unchanged.')

if __name__=='__main__':
    try:main()
    except Exception as e:
        print('Incident confirmation failed: '+type(e).__name__,file=sys.stderr);sys.exit(1)
