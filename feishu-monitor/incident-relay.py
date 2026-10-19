"""Event relay only: monitoring hash outbox -> confirmed Feishu delivery.

No collectors, tasks, SQL, browser profiles, or scheduled jobs are controlled.
At-least-once delivery: a crash after HTTP success but before Redis commit may
repeat the same incident ID. Unconfirmed events never advance the cursor.
"""
import argparse
import json
import os
import secrets
import sys
import time
from pathlib import Path
from urllib.parse import urlparse, urlunparse, quote
sys.path.insert(0,str(Path(__file__).resolve().parent))
from collect import ROOT, RedisConnection, atomic_json
from publish import send
from monitor_paths import platform_path

LEASE="""
local t=redis.call('TIME');local now=tonumber(t[1])*1000+math.floor(tonumber(t[2])/1000)
local token=redis.call('HGET',KEYS[1],'relayToken')
local until_ms=tonumber(redis.call('HGET',KEYS[1],'relayUntil')) or 0
if token and token~=ARGV[1] and until_ms>now then return 0 end
redis.call('HSET',KEYS[1],'relayToken',ARGV[1],'relayUntil',now+60000)
return 1
"""
COMMIT="""
if redis.call('HGET',KEYS[1],'relayToken')~=ARGV[1] then return redis.error_reply('RELAY_LEASE_LOST') end
if redis.call('HGET',KEYS[2],ARGV[2])~=ARGV[4] then return redis.error_reply('RELAY_EVENT_CHANGED') end
redis.call('HSET',KEYS[1],ARGV[2],ARGV[3]);redis.call('HDEL',KEYS[2],ARGV[2]);return 1
"""

def payload(event):
    if event.get('kind') not in ('login','captcha','security','database') or not event.get('incidentId'):
        raise ValueError('Invalid incident schema')
    if event.get('kind')=='database':
        # Import the same whitelist/hints as the worker; no raw SQL/driver text.
        sys.path.insert(0,str(platform_path('视频号')/'common/src'))
        from database_diagnostics import safe_code, advice, STAGES
        code=safe_code(event.get('errorCode'))
        resolved=event.get('status')=='resolved' and event.get('databaseReadbackVerified') is True
        stage=event.get('stage') if event.get('stage') in STAGES else 'unknown'
        text=(f"平台：{event['platform']}\n机器：{event['machine']} / {event['workerId']}\n"
              f"状态：{'数据库真实查询已恢复' if resolved else '数据库回读链路失败'}\n"
              f"阶段：{stage} · 错误码：{code}\n"
              f"下一步：{'无需重复处理；任务是否完成以原验收记录为准' if resolved else advice(code)}\n"
              '本告警不领取、重置或确认任务。\n'
              f"事件：{event['incidentId']}")
        return {'msg_type':'interactive','card':{'header':{'template':'green' if resolved else 'red',
            'title':{'tag':'plain_text','content':'采集数据库回读已恢复' if resolved else '采集数据库回读异常'}},
            'elements':[{'tag':'div','text':{'tag':'plain_text','content':text}}]}}
    resolved=event.get('status')=='resolved'
    title='采集人工处理已确认' if resolved else '采集需要人工处理'
    if event.get('test'):
        title='【联调测试】采集人工处理告警'
    labels={'login':'登录失效，请在对应机器完成登录', 'captcha':'出现验证码，请在对应机器人工验证',
            'security':'安全限制，自动冷却等待'}
    text=(f"平台：{event['platform']}\n机器：{event['machine']} / {event['workerId']}\n"
          f"状态：{'人工已确认；下次采集仍须正常校验页面' if resolved else labels[event['kind']]}\n"
          f"任务：{event.get('keyword') or '当前节点'}\n"
          f"下一步：{'无需重复确认' if resolved else '完成操作后运行对应节点的“确认人工处理”命令；不要清空或重置任务'}\n"
          f"事件：{event['incidentId']}")
    if event.get('test'):
        text='模拟验证码告警；并非真实平台故障，无需人工处理。\n'+text.replace('完成操作后运行对应节点的“确认人工处理”命令；不要清空或重置任务','测试完成，无需操作')
    return {'msg_type':'interactive','card':{'header':{'template':'green' if resolved else 'orange',
        'title':{'tag':'plain_text','content':title}},'elements':[{'tag':'div','text':{'tag':'plain_text','content':text}}]}}

def deliver_source(c,namespace,token,webhook,secret='',sender=send):
    stream,delivery=namespace+':monitor:outbox',namespace+':monitor:delivery'
    if not c.command('EVAL',LEASE,1,delivery,token):
        return {'state':'standby','delivered':0}
    values=c.command('HVALS',stream) or []
    rows=[]
    for raw in values:
        event=json.loads(raw)
        rows.append((event['incidentId']+('|resolved' if event['status']=='resolved' else '|active'),raw))
    rows.sort(key=lambda r:(json.loads(r[1]).get('startedAt',0),json.loads(r[1]).get('status')=='resolved',r[0]))
    delivered=0
    for mid,raw in rows[:20]:
        # Renew before the bounded HTTP call; only our token can commit.
        if not c.command('EVAL',LEASE,1,delivery,token):
            raise RuntimeError('Relay lease lost')
        event=json.loads(raw)
        if sender(payload(event),webhook,secret) is not True:
            raise RuntimeError('Feishu delivery not confirmed')
        receipt={'incidentId':event['incidentId'],'status':event['status'],
                 'confirmedAt':time.time(),'deliveryConfirmed':True}
        c.command('EVAL',COMMIT,2,delivery,stream,token,mid,json.dumps(receipt),raw)
        delivered+=1
        print('Feishu delivery confirmed; incident='+event['incidentId'],flush=True)
    return {'state':'ready','delivered':delivered}

def sources():
    config=json.loads((ROOT/'config.json').read_text(encoding='utf-8-sig'))
    result=[]
    for platform,default,prefix,env in [('小红书','xiaohongshu','xhs','MONITOR_XHS_PASSWORD'),('抖音','douyin','xhs:douyin','MONITOR_DY_PASSWORD')]:
        common=platform_path(platform,config=config)/'common'
        settings=json.loads((common/'redis-config.json').read_text(encoding='utf-8-sig'))
        manifest=json.loads((common/'tasks/redis-tasks.json').read_text(encoding='utf-8-sig'))
        campaign=settings.get('taskPoolCampaign') or settings['campaign']+'-mysql-'+manifest['manifestHash'][:16]
        u=urlparse(settings['url'])
        if u.username or u.password:
            raise ValueError('Credential-bearing URL forbidden')
        if settings.get('username'):
            u=u._replace(netloc=quote(settings['username'],safe='')+'@'+u.netloc)
        result.append((platform,prefix+':{'+campaign+'}',urlunparse(u),os.environ.get(env)))
    password=(ROOT/config['redis_credential']).read_text(encoding='utf-8-sig').strip()
    result.append(('视频号','wechat:channels:'+config['run_id'],config['redis_url'],password))
    return result

def main():
    p=argparse.ArgumentParser();p.add_argument('--once',action='store_true');p.add_argument('--check',action='store_true');a=p.parse_args()
    if a.check:
        health={}
        for platform,namespace,url,password in sources():
            try:
                if not password:raise RuntimeError('Existing Redis credential unavailable')
                with RedisConnection(url,password,timeout=5) as c:
                    c.command('TIME')
                    health[platform]={'state':'ready','outboxCount':len(c.command('HVALS',namespace+':monitor:outbox') or [])}
            except Exception as e:health[platform]={'state':'failed','errorType':type(e).__name__}
        print(json.dumps({'readOnly':True,'sources':health},ensure_ascii=False),flush=True)
        return int(any(v['state']=='failed' for v in health.values()))
    if not os.environ.get('FEISHU_WEBHOOK'):
        raise RuntimeError('Existing encrypted Feishu credential required')
    token=secrets.token_hex(24);previous=None
    configured=sources()
    stop_file=ROOT/'output/incident-relay.stop'
    while not stop_file.exists():
        health={}
        for platform,namespace,url,password in configured:
            try:
                if not password:raise RuntimeError('Existing Redis credential unavailable')
                with RedisConnection(url,password,timeout=5) as c:
                    health[platform]=deliver_source(c,namespace,token,os.environ['FEISHU_WEBHOOK'],os.environ.get('FEISHU_SIGN_SECRET',''))
            except Exception as e:
                health[platform]={'state':'failed','errorType':type(e).__name__,'deliveryConfirmed':False}
        signature={k:(v['state'],v.get('errorType')) for k,v in health.items()}
        atomic_json(ROOT/'output/incident-relay-status.json',{'pid':os.getpid(),'updatedAt':time.time(),'sources':health})
        if signature!=previous:
            print(json.dumps({'event':'incident_relay_health','sources':health},ensure_ascii=False),flush=True);previous=signature
        if a.once:return int(any(v['state']=='failed' for v in health.values()))
        for _ in range(30):
            if stop_file.exists():break
            time.sleep(0.1)
    atomic_json(ROOT/'output/incident-relay-status.json',{'pid':os.getpid(),'updatedAt':time.time(),'state':'stopped','sources':{}})
    return 0

if __name__=='__main__':
    try:sys.exit(main())
    except Exception as e:
        print('Incident relay failed: '+type(e).__name__,file=sys.stderr);sys.exit(1)
