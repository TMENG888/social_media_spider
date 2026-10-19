"""Monitoring-only incident state and interruptible waits; no task mutation."""
import hashlib
import json
import os
import re
import socket
import sys
import time
from pathlib import Path
SRC_DIR = Path(__file__).resolve().parent
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))
SCRIPT=Path(__file__).with_name('operational-incident.lua').read_text(encoding='utf-8')
KEYS=('{collector-monitor-v1}:incidents','{collector-monitor-v1}:outbox')
def classify_restriction(error):
    text=str(error)
    if re.search(r'LOGIN_REQUIRED|login_required|请先登录|请人工登录|扫码登录',text):
        return {'kind':'login','requiresHuman':True}
    if re.search(r'验证码|滑块|拼图|请完成.*验证|安全验证|验证弹窗|captcha',text,re.I):
        return {'kind':'captcha','requiresHuman':True}
    if re.search(r'SECURITY_CHALLENGE|PLATFORM_RESTRICTION|访问频繁|操作频繁|访问过于频繁|300013|安全限制|网络环境存在风险|暂时无法浏览',text):
        return {'kind':'security','requiresHuman':False}
    return None
class OperationalGate:
    def __init__(self,command,worker_id,platform='视频号',machine=None,keys=KEYS):
        self.command,self.worker_id,self.platform,self.keys=command,worker_id,platform,keys
        self.machine=machine or socket.gethostname()
        self.field=hashlib.sha256('|'.join((platform,self.machine,worker_id)).encode()).hexdigest()
    def call(self,action,value='',cooldown_ms=7200000):
        return json.loads(self.command('EVAL',SCRIPT,2,*self.keys,action,self.field,
            value if isinstance(value,str) else json.dumps(value,ensure_ascii=False),cooldown_ms))
    def read(self):
        return self.call('read')
    def record(self,error,task_id='',keyword='',cooldown_ms=7200000):
        kind=classify_restriction(error)
        if not kind:
            return None
        return self.call('record',dict(kind,field=self.field,platform=self.platform,machine=self.machine,
            workerId=self.worker_id,taskId=str(task_id)[:180],keyword=str(keyword)[:180]),cooldown_ms)
    def resolve(self):
        return self.call('resolve','operator_confirmed')
    def wait(self,should_stop=lambda:False,poll_seconds=3):
        while not should_stop():
            s=self.read()
            if s['status'] in ('ready','resolved') or (not s.get('requiresHuman') and s['cooldownUntil']<=s['serverTime']):
                return True
            time.sleep(poll_seconds)
        return False
def report_from_environment(error):
    if not os.environ.get('REDIS_URL'):
        return None
    from redis_task_queue import redis_command
    cmd=lambda *p:redis_command(os.environ['REDIS_URL'],os.environ.get('REDIS_PASSWORD'),*p,timeout=5)
    prefix='wechat:channels:'+os.environ.get('WECHAT_REDIS_RUN_ID',os.environ.get('REDIS_RUN_ID',''))
    return OperationalGate(cmd,os.environ.get('WECHAT_WORKER_ID','worker-unknown'),keys=(prefix+':monitor:incidents',prefix+':monitor:outbox')).record(
        error,os.environ.get('WECHAT_REDIS_TASK_ID',''),os.environ.get('WECHAT_REDIS_KEYWORD',''))

if __name__=='__main__':
    try:
        from redis_task_queue import redis_command
        prefix='wechat:channels:'+os.environ.get('WECHAT_REDIS_RUN_ID',os.environ.get('REDIS_RUN_ID',''))
        cmd=lambda *p:redis_command(os.environ['REDIS_URL'],os.environ.get('REDIS_PASSWORD'),*p,timeout=5)
        state=OperationalGate(cmd,os.environ['WECHAT_WORKER_ID'],keys=(prefix+':monitor:incidents',prefix+':monitor:outbox')).read()
        active=state.get('requiresHuman') or state.get('cooldownUntil',0)>state['serverTime']
        sys.exit(76 if state.get('status')!='resolved' and active else 0)
    except (OSError, TimeoutError) as e:
        print('Operational Redis unavailable: '+type(e).__name__,file=sys.stderr);sys.exit(75)
    except Exception as e:
        print('Operational check failed: '+type(e).__name__,file=sys.stderr);sys.exit(1)
