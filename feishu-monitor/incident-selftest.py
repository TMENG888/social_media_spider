"""One clearly labelled test card; UUID monitoring fixture, never real tasks."""
import importlib.util
import json
import os
import secrets
import sys
import uuid
from pathlib import Path
spec=importlib.util.spec_from_file_location('incident_relay',Path(__file__).with_name('incident-relay.py'))
relay=importlib.util.module_from_spec(spec);spec.loader.exec_module(relay)
from operational_gate import OperationalGate

def main():
    platform,base,url,password=relay.sources()[0]
    namespace=base+':incident-selftest-'+uuid.uuid4().hex
    keys=(namespace+':monitor:incidents',namespace+':monitor:outbox')
    with relay.RedisConnection(url,password,timeout=5) as c:
        gate=OperationalGate(c.command,'fixture-only',platform=platform,machine='TEST-ONLY',keys=keys)
        event_key=None
        try:
            event=gate.call('record',{'field':gate.field,'kind':'captcha','requiresHuman':True,
                'platform':platform,'machine':'TEST-ONLY','workerId':'fixture-only',
                'keyword':'【测试】Redis记录 → 飞书送达确认','taskId':'','test':True})
            event_key=event['incidentId']+'|active'
            result=relay.deliver_source(c,namespace,secrets.token_hex(24),os.environ['FEISHU_WEBHOOK'],os.environ.get('FEISHU_SIGN_SECRET',''))
            receipt=json.loads(c.command('HGET',namespace+':monitor:delivery',event_key))
            if result['delivered']!=1 or receipt['deliveryConfirmed'] is not True or c.command('HGET',keys[1],event_key):
                raise RuntimeError('Selftest delivery readback failed')
            relay.atomic_json(relay.ROOT/'output/incident-selftest.json',{'test':True,'receipt':receipt,'result':result,'taskKeysTouched':False})
            print('Redis delivery receipt and outbox removal verified; no task state changed.')
        finally:
            c.command('HDEL',keys[0],gate.field,'__sequence__')
            if event_key:
                c.command('HDEL',keys[1],event_key)
                c.command('HDEL',namespace+':monitor:delivery','relayToken','relayUntil',event_key)

if __name__=='__main__':
    try:main()
    except Exception as e:
        print('Incident selftest failed: '+type(e).__name__,file=sys.stderr);sys.exit(1)
