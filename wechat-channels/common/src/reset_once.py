"""One fresh original-keyword recollection, with distinct business completion."""
import json
import re
import secrets
from pathlib import Path

POLICY='reset-once-20261016-v1'
SCRIPT=Path(__file__).with_name('reset-once.lua').read_text(encoding='utf-8')

def protected(record):
    return bool(record.get('stopped') or re.search(
        r'LOGIN|CAPTCHA|SECURITY_CHALLENGE|PLATFORM_RESTRICTION|COOLDOWN|RATE_LIMIT|STOP_REQUESTED|partial_stopped|risk_controlled|验证码|登录|人工停止',
        str(record.get('error',''))+' '+str(record.get('status','')),re.I))

class ResetOncePolicy:
    def __init__(self,command,args):
        self.command,self.args=command,args
        p=args.prefix
        self.keys=[p+':recollection-once',p+':recollection-history',args.status_key,p+':volume-attempts',
            p+':volume-lease-tokens',p+':recollection-owners',args.stream,p+':recollection-leases',
            args.status_key,p+':recollection-errors',p+':recollection-failed',p+':recollection-baseline',args.status_key]

    def call(self,mode,task_id,mid,*,token='',record=None,expected=''):
        a=self.args
        return json.loads(self.command('EVAL',SCRIPT,len(self.keys),*self.keys,mode,task_id,'stream',token,
            a.consumer,mid,a.group,task_id+'|nonzero-p80-20261015-v1',json.dumps(record or {},ensure_ascii=False),
            expected,str(a.reclaim_idle_seconds*1000)))

    def prepare(self,task_id,mid):
        token=secrets.token_hex(24)
        result=self.call('prepare',task_id,mid,token=token)
        if result.get('status')=='claimed':result['token']=token
        return result

    def finish(self,task_id,mid,token,record):
        return self.call('pause' if protected(record) else 'finish',task_id,mid,token=token,record=record)
