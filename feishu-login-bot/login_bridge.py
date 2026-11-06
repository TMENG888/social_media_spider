"""Deterministic Feishu login bridge. No model, arbitrary URL or shell commands."""
from __future__ import annotations
import concurrent.futures
from datetime import datetime, timedelta, timezone
import hashlib
import json
import logging
import os
import shutil
from pathlib import Path
import re
import subprocess
import threading
import time
import uuid

LOG = logging.getLogger('feishu_luna.login_bridge')
ROOTS = {f'work{i:02d}': fr'\\work{i:02d}\collector' for i in range(1,5)}
PATTERN = re.compile(r'^(刷新登录|登录截图|登录状态)\s+(work0[1-4])\s+(小红书|抖音)(?:\s+(worker-0[1-5]))?$', re.I)
ACTIVE = {'sms_requesting','sms_send_failed','sms_send_unconfirmed','waiting_sms','sms_opening','sms_submitted','sms_rejected','sms_expired','sms_manual','opening','waiting_scan','qr_expired','qr_unavailable','verifying','manual_captcha','manual_security','manual_gateway','unavailable'}
TERMINAL = {'verified','cancelled'}
LABELS = {'sms_requesting':'正在请求平台发送短信，尚未确认受理','sms_send_failed':'平台未确认接受本次短信发送，请检查验证页面','sms_send_unconfirmed':'未取得本次短信发送的成功响应，无法确认短信已发送','waiting_sms':'平台已确认受理本次短信发送，请查看绑定手机；实际送达以手机为准','sms_opening':'正在打开短信验证','sms_submitted':'短信验证码已提交，等待登录和原搜索核验','sms_rejected':'页面提示验证码错误或失效，请检查最新短信后重新提供','sms_expired':'短信验证等待已超时，请在该机器检查登录页面','sms_manual':'未确认短信发送结果，请在该机器检查验证页面，程序不会重复发送','opening':'正在打开登录页面','waiting_scan':'请扫码登录','qr_expired':'二维码过期，请刷新登录',
 'qr_unavailable':'尚未识别到可分享的二维码，请在该机器检查登录窗口',
 'verifying':'正在核验账号和原检索词访问权限','manual_captcha':'需要在该机器完成人工验证码',
 'manual_security':'出现安全限制，保留保护，不允许刷新解除','manual_gateway':'平台网关暂时异常',
 'unavailable':'登录会话暂不可用，保护保持原样','verified':'登录核验通过；采集恢复尚待确认',
 'cancelled':'登录窗口已关闭或恢复取消，未解除保护','resumed':'原监督器已启动后续 worker，并已进入关键词采集'}

def notice_content(title, rows, phase, message_type='interactive'):
    if message_type=='post':return {'zh_cn':{'title':title,'content':rows}}
    elements=[]
    for row in rows:
        for part in row:
            if part['tag']=='text':elements.append({'tag':'markdown','content':part['text']})
            elif part['tag']=='img':elements.append({'tag':'img','img_key':part['image_key'],'alt':{'tag':'plain_text','content':'登录二维码'}})
    color='green' if phase in {'verified','resumed'} else 'grey' if phase in {'cancelled','resolved'} else 'orange'
    label={'waiting_scan':'请扫码登录','qr_expired':'二维码已过期','waiting_sms':'请提供短信验证码','sms_rejected':'请核对短信验证码','manual_captcha':'需要人工验证','manual_security':'需要检查安全限制','verified':'登录核验通过','resumed':'采集已恢复'}.get(phase)
    header_title=title+('｜'+label if label else '')
    return {'config':{'wide_screen_mode':True},'header':{'template':color,'title':{'tag':'plain_text','content':header_title}},'elements':elements}

def read_json(p):
    if p.stat().st_size > 65536:
        raise ValueError('oversized_state')
    return json.loads(p.read_text(encoding='utf-8-sig'))

def atomic(p, value):
    p = Path(p)
    temp = p.with_name(p.name + '.' + str(uuid.uuid4()) + '.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
    os.replace(temp, p)

def fresh(s, now=None):
    now = time.time()*1000 if now is None else now
    return isinstance(s.get('updatedAt'), (int,float)) and -5000 <= now-s['updatedAt'] <= 45000

def with_resume(root,s):
    if s['phase']!='verified':
        return s
    try:
        r=read_json(root/'resume.json')
        if (r.get('schema')==1 and r.get('sessionId')==s['sessionId'] and r.get('machine')==s['machine']
            and r.get('platform')==s['platform'] and r.get('workerId')==s['workerId']
            and r.get('supervisor')==s.get('supervisor') and s.get('supervisor')
            and r.get('evidence')==('original_supervisor_content_imported' if s['platform']=='抖音' else 'original_supervisor_worker_entered_keyword')
            and s.get('verifiedAt',float('inf'))<=r['at']<=time.time()*1000
            and time.time()*1000-r['at']<300000):
            if s['platform']=='抖音':
                # A claimed task is not progress, and an old receipt must not
                # announce success after the same worker has hit a challenge.
                run=read_json(root.parent.parent/'runs'/'worker_status.json')
                sup=read_json(root.parent/'monitor-supervisor.json')
                sup_at=datetime.fromisoformat(sup['updatedAt'].replace('Z','+00:00')).timestamp()*1000
                if (run.get('status')!='running' or run.get('operationalHold') or run.get('fatalError')
                    or run.get('currentKeyword')!=r.get('keyword')
                    or not datetime.fromisoformat(run['startedAt'].replace('Z','+00:00')).timestamp()*1000<=r['at']
                    or sup.get('sessionId')!=s['supervisor']['sessionId'] or sup.get('state')!='collecting'
                    or not -5000<=time.time()*1000-sup_at<=86400000):
                    return s
            return {**s,'phase':'resumed','resume':r}
    except (OSError, ValueError, TypeError, KeyError):
        pass
    return s

def valid_account(a,s):
    return (isinstance(a,dict) and a.get('schema')==1 and a.get('platform')==s.get('platform')
            and a.get('workerId')==s.get('workerId') and a.get('hostname')==s.get('hostname')
            and isinstance(a.get('hostname'),str) and a.get('profile')=='browser-profile'
            and a.get('source') in {'authenticated_self_response','authenticated_current_user_state'}
            and isinstance(a.get('nickname'),str) and 0<len(a['nickname'].strip())<=80
            and not any(ord(c)<32 or 127<=ord(c)<=159 or c in '\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069' for c in a['nickname'])
            and isinstance(a.get('observedAt'),(int,float)) and 0<a['observedAt']<=time.time()*1000+5000)

def qr_has_symbol(data):
    # A changing qrcode DOM region can contain a phone-confirmation overlay.
    # Fail closed on decoder failure; no image or payload leaves this machine.
    try:
        node=os.environ.get('LOGIN_BRIDGE_NODE') or shutil.which('node') or 'node'
        helper=Path(__file__).with_name('qr-validation')/'validate-qr.cjs'
        result=subprocess.run([node,str(helper)],input=data,capture_output=True,timeout=10,
                              creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        return result.returncode==0 and result.stdout==b'1'
    except (OSError,subprocess.TimeoutExpired):
        return False

class LoginBridge:
    def __init__(self, lark, cfg, stop, roots=None, cache=None):
        self.lark, self.cfg, self.stop = lark, cfg, stop
        self.roots = roots if roots is not None else cfg.get('machine_roots',ROOTS)
        self.bot_mention = cfg.get('bot_mention','@机器人')
        self.cache = Path(cache or cfg.get('login_cache_dir') or Path(cfg.get('runtime_dir',Path(__file__).parent/'runtime'))/'login-bridge')
        self.cache.mkdir(parents=True, exist_ok=True)
        self.state_file = self.cache/'delivery-state.json'
        self.state = read_json(self.state_file) if self.state_file.exists() else {}
        self.reminder_file = self.cache/'qr-reminders.json'
        self.reminders = read_json(self.reminder_file) if self.reminder_file.exists() else {}
        self.observation_file = self.cache/'qr-observations.json'
        self.observations = read_json(self.observation_file) if self.observation_file.exists() else {}
        self.attention_file = self.cache/'attention-reminder.json'
        self.attention_reminder = read_json(self.attention_file) if self.attention_file.exists() else {}
        self.attention_snapshots = {}
        self.lock = threading.RLock()
        self.targets = {m: threading.Lock() for m in self.roots}
        self.node_targets = {(m,p):threading.Lock() for m in self.roots for p in ('小红书','抖音')}
        self.health = {}
        self.threads = []

    def target_lock(self, machine, platform):
        return self.node_targets[(machine,platform)]

    def sessions(self, machine):
        out=[]
        if not Path(self.roots[machine]).is_dir():
            raise OSError('machine_share_unavailable')
        for platform in ('小红书','抖音'):
            for i in range(1,6):
                worker=f'worker-{i:02d}'
                root=Path(self.roots[machine])/platform/worker/'.state'/'login-bridge'
                try:
                    s=read_json(root/'session.json')
                    if (s.get('schema')!=1 or s.get('machine')!=machine or s.get('platform')!=platform or s.get('workerId')!=worker
                        or str(uuid.UUID(s['sessionId']))!=s['sessionId'] or s.get('phase') not in ACTIVE|TERMINAL):
                        continue
                    if fresh(s):
                        out.append((root,s))
                    elif s['phase'] in TERMINAL and 0 <= time.time()*1000-s['updatedAt'] < 86400000:
                        out.append((root,s))
                except (OSError, ValueError, KeyError, TypeError):
                    continue
        return out

    def _send(self, root, s, force_key=None):
        # Closure/cancellation is bookkeeping, not a new action for the group.
        # Keep the session and incident identifiers in the local session state.
        if s['phase']=='cancelled':
            return None
        if s['phase'] in {'waiting_sms','sms_rejected'} and (s.get('smsRequest') or {}).get('accepted') is not True:
            raise ValueError('sms_send_not_confirmed')
        image=s.get('image') if s['phase']=='waiting_scan' else None
        category = ('qr:'+str(s['generation'])) if image else s['phase']
        if s['phase'] in {'waiting_sms','sms_rejected'}:category += ':'+str((s.get('sms') or {}).get('challengeId'))+':'+str((s.get('sms') or {}).get('attempts',0))
        if s['phase'] in {'sms_send_failed','sms_send_unconfirmed'}:category += ':'+str((s.get('smsRequest') or {}).get('requestedAt',0))
        # A QR version is one delivery regardless of automatic polling or the
        # human command that caused it. Both paths share the same persisted key.
        key=f"{self.cfg['chat_id']}:{s['sessionId']}:{category if image else (force_key or category)}"
        with self.lock:
            resume_target=None
            if s['phase']=='resumed':
                resume_target=[s['machine'],s['platform'],s['workerId'],s.get('resume',{}).get('keyword')]
                for delivered in self.state.values():
                    if (delivered.get('status')=='sent' and delivered.get('chat_id')==self.cfg['chat_id'] and delivered.get('resumeTarget')==resume_target
                        and 0<=time.time()-delivered.get('sentAt',0)<1800):
                        return delivered.get('message_id')
            item=self.state.get(key)
            if item and item.get('status')=='rejected_non_qr':
                return None
            if item and item.get('status')=='sent':
                return item.get('message_id')
            if item and time.time()-item['firstAttempt']>=3300:
                # Never retry beyond Feishu's one-hour idempotency window.
                raise RuntimeError('delivery_unconfirmed_requires_review')
            if item and item.get('retryAt',0)>time.time():
                raise RuntimeError('delivery_retry_backoff')
            if not item:
                item={'status':'pending','firstAttempt':time.time(),'uuid':str(uuid.uuid5(uuid.NAMESPACE_URL,'crawler-login:'+key))}
            item['chat_id']=self.cfg['chat_id']
            if resume_target:item['resumeTarget']=resume_target
            item['retryAt']=time.time()+60
            self.state[key]=item
            atomic(self.state_file,self.state)
            title=f"{s['machine']} · {s['platform']}"
            account_config=self.cfg.get('machine_accounts',{}).get(s['machine']) or {}
            nickname=(account_config.get('platforms',{}).get(s['platform']) or {}).get('nickname','')
            if isinstance(nickname,str) and 0<len(nickname)<=80 and not any(ord(c)<32 or 127<=ord(c)<=159 for c in nickname):title+=' · '+nickname
            phone=account_config.get('phone','')
            if isinstance(phone,str) and re.fullmatch(r'1\d{10}',phone):title+=' · '+phone
            text=LABELS.get(s['phase'],s['phase'])
            if s['phase']=='verified' and not s.get('supervisor'):
                text='登录核验通过；尚未确认采集启动'
            if s['phase']=='resumed':
                if s['platform']=='抖音':text='后续采集已取得内容并确认入库'
                text+='；当前关键词：'+str(s.get('resume',{}).get('keyword','待核'))
            if s['phase']=='qr_expired':
                text+=f"\n请 {self.bot_mention} 刷新登录 {s['machine']} {s['platform']}"
            if s['phase'] in {'sms_send_failed','sms_send_unconfirmed','sms_expired'}:
                text+=f"\n若未收到短信，请 {self.bot_mention} 重发验证码 {s['machine']} {s['platform']}。每次人工指令只尝试一次，至少间隔60秒。"
                receipt=s.get('smsRequest') or {}
                if receipt.get('httpStatus') is not None:
                    text+=f"\n平台响应 HTTP {receipt['httpStatus']}；业务状态 {receipt.get('platformCode','未识别')}。"
            if s['phase'] in {'waiting_sms','sms_rejected'}:
                current=read_json(root/'session.json')
                if not fresh(current) or current['sessionId']!=s['sessionId'] or current['phase']!=s['phase'] or current.get('sms')!=s.get('sms'):raise ValueError('sms_state_changed')
                if (s.get('sms') or {}).get('expiresAt',0)<=time.time()*1000:raise ValueError('sms_expired')
                text+=f"\n请 {self.bot_mention} 验证码 {s['machine']} {s['platform']} 加上短信中的数字验证码。\n验证码只用于本次登录；飞书群中原消息仍会保留。"
            if image:
                captured=datetime.fromtimestamp(image['capturedAt']/1000,timezone(timedelta(hours=8)))
                text+='\n二维码截图时间：'+captured.strftime('%Y-%m-%d %H:%M:%S')+'（北京时间）'
            rows=[[{'tag':'text','text':text}]]
            if image:
                name=image.get('filename','')
                if not re.fullmatch(r'qr-'+re.escape(s['sessionId'])+r'-\d+\.png',name):
                    raise ValueError('invalid_image_path')
                f=root/name
                if f.stat().st_size>2_000_000:
                    raise ValueError('oversized_image')
                data=f.read_bytes()
                if not data.startswith(b'\x89PNG\r\n\x1a\n') or hashlib.sha256(data).hexdigest()!=image.get('sha256'):
                    raise ValueError('image_integrity_failed')
                if not qr_has_symbol(data):
                    item.update(status='rejected_non_qr',reason='NO_DECODABLE_QR_SYMBOL')
                    atomic(self.state_file,self.state)
                    return None
                if not -5000 <= time.time()*1000-image['capturedAt'] <= 180000:
                    raise ValueError('stale_qr')
                # Recheck live session immediately before sending a login credential.
                current=read_json(root/'session.json')
                if not fresh(current) or current['sessionId']!=s['sessionId'] or current.get('image')!=image or current['phase']!='waiting_scan':
                    raise ValueError('session_changed_before_upload')
                local=self.cache/name
                local.write_bytes(data)
                if not item.get('image_key'):
                    upload=self.lark.call(['im','images','create','--data',json.dumps({'image_type':'message'}),'--file',local.name,'--as','bot'],cwd=self.cache)
                    image_key=upload.get('image_key') or upload.get('data',{}).get('image_key')
                    if not image_key:
                        raise ValueError('image_upload_not_confirmed')
                    item['image_key']=image_key
                    atomic(self.state_file,self.state)
                # Stale screenshots must not be sent if upload took too long.
                current=read_json(root/'session.json')
                if not fresh(current) or current.get('image')!=image or current['phase']!='waiting_scan':
                    raise ValueError('session_changed_during_upload')
                rows.append([{'tag':'img','image_key':item['image_key']}])
                after_scan='扫码后仍需程序核验；人工停止、安全限制及冷却保持原样。'
                if self._paused_login_authorized(root,s):
                    authorization=read_json(root/'login-only-authorized.json')
                    after_scan=('扫码后核验通过，将按本次授权交回原采集监督器；安全限制和冷却保持原样。'
                                if authorization.get('purpose')=='login_before_authorized_restart' else
                                '扫码后仅恢复登录，采集仍暂停；安全限制及冷却保持原样。')
                rows.append([{'tag':'text','text':f"过期请 {self.bot_mention} 刷新登录 {s['machine']} {s['platform']}\n{after_scan}"}])
            message_type='interactive'
            post=notice_content(title,rows,s['phase'])
            verified_item=self.state.get(f"{self.cfg['chat_id']}:{s['sessionId']}:verified",{})
            if s['phase']=='resumed' and verified_item.get('status')=='sent' and verified_item.get('message_id'):
                # Update the single success card when actual collection evidence
                # arrives, instead of posting a second success notification.
                message_id=verified_item['message_id']
                message_type=verified_item.get('message_type','post')
                post=notice_content(title,rows,s['phase'],message_type)
                self.lark.call(['im','+messages-edit','--message-id',message_id,'--msg-type',message_type,'--content','-','--as','bot'],stdin=json.dumps(post,ensure_ascii=False))
                item.update(status='sent',message_id=message_id,message_type=message_type,sentAt=time.time(),editedVerified=True)
                atomic(self.state_file,self.state)
                return message_id
            result=self.lark.call(['im','+messages-send','--chat-id',self.cfg['chat_id'],'--msg-type',message_type,'--content','-','--as','bot','--idempotency-key',item['uuid']],stdin=json.dumps(post,ensure_ascii=False))
            message_id=result.get('message_id') or result.get('message',{}).get('message_id')
            if not message_id:
                raise ValueError('message_delivery_not_confirmed')
            item.update(status='sent',message_id=message_id,message_type=message_type,sentAt=time.time())
            atomic(self.state_file,self.state)
            return message_id

    def _paused_login_authorized(self, root, s, now=None):
        """A bounded explicit login window may run while collection stays stopped."""
        now=time.time()*1000 if now is None else now
        try:
            a=read_json(root/'login-only-authorized.json')
            if (a.get('schema')!=1 or a.get('purpose') not in {'login_only_paused','login_before_authorized_restart'}
                or not isinstance(a.get('createdAt'),(int,float)) or not isinstance(a.get('expiresAt'),(int,float))
                or not a['createdAt']<=now<a['expiresAt'] or a['expiresAt']-a['createdAt']>12*3600000
                or any(a.get(k)!=s.get(k) for k in ('sessionId','pid','machine','platform','workerId','hostname'))
                or not isinstance(s.get('pid'),int) or not fresh(s,now)):
                return False
            return all(hashlib.sha256((root.parent/n).read_bytes()).hexdigest()==a.get('stopHashes',{}).get(n)
                       for n in ('supervisor.stop','stop.requested'))
        except (OSError,ValueError,TypeError,KeyError):
            return False

    def _qr_due(self, root, s, now=None):
        """Keep 8-second observations; remind on the configured interval.

        Only the original live bridge can refresh its browser and acknowledge
        the new generation. No new login browser, task, or verification attempt
        is started by this reminder.
        """
        now=time.time() if now is None else now
        interval=max(60,min(86400,int(self.cfg.get('qr_reminder_interval_seconds',600))))
        if s['phase'] not in {'waiting_scan','qr_expired'} or not fresh(s,now*1000):return False
        if (root.parent/'supervisor.stop').exists() and not self._paused_login_authorized(root,s,now*1000):return False
        prefix=self.cfg['chat_id']+':'+s['sessionId']+':qr:'
        with self.lock:
            delivered=[v for k,v in self.state.items() if k.startswith(prefix) and v.get('status')=='sent']
            last=max((v['sentAt'] for v in delivered),default=None)
            key='|'.join([self.cfg['chat_id'],s['machine'],s['platform'],s['workerId']])
            r=self.reminders.get(key,{})
            if r.get('sessionId')!=s['sessionId']:r={'sessionId':s['sessionId']}
            pending=r.get('pending')
            if pending:
                ack=s.get('ack') or {}
                if ack.get('commandId')==pending['commandId']:
                    if (ack.get('ok') is True and s.get('generation',0)>pending['generation']
                        and s['phase']=='waiting_scan' and s.get('image')
                        and s['image'].get('capturedAt',0)>=pending['issuedAt']):
                        # Normal _send() still verifies hash, QR decode, age,
                        # and live browser state before any upload.
                        if last is not None and last>=pending['issuedAt']/1000:
                            r.pop('pending',None)
                        else:return True
                    else:
                        r.pop('pending',None);r['retryAfter']=now+interval
                elif now*1000<=pending['expiresAt']:return False
                else:r.pop('pending',None);r['retryAfter']=now+interval
                self.reminders[key]=r;atomic(self.reminder_file,self.reminders)
            if now<r.get('retryAfter',0):return False
            if last is None and s['phase']=='waiting_scan' and s.get('image') and -5<=now-s['image'].get('capturedAt',0)/1000<=180:
                return True
            anchor=last if last is not None else s.get('createdAt',now*1000)/1000
            if now-anchor<interval:return False
            current=read_json(root/'session.json')
            if (not fresh(current,now*1000) or current['sessionId']!=s['sessionId']
                or current['phase'] not in {'waiting_scan','qr_expired'}):return False
            # Do not replace a human command that has not been acknowledged.
            try:
                command=read_json(root/'command.json')
                if (command.get('expiresAt',0)>now*1000 and command.get('commandId')!=(current.get('ack') or {}).get('commandId')):return False
            except FileNotFoundError:pass
            issued=int(now*1000)
            command={'commandId':str(uuid.uuid4()),'action':'refresh','sessionId':s['sessionId'],
                     'machine':s['machine'],'platform':s['platform'],'workerId':s['workerId'],
                     'issuedAt':issued,'expiresAt':issued+45000}
            r['pending']={**command,'generation':s.get('generation',0)}
            self.reminders[key]=r;atomic(self.reminder_file,self.reminders)
            atomic(root/'command.json',command)
            return False

    def _qr_warning_due(self, s, now=None):
        """QR rendering is asynchronous: require two continuous minutes first."""
        now=time.time() if now is None else now
        key='|'.join([self.cfg['chat_id'],s['machine'],s['platform'],s['workerId']])
        with self.lock:
            previous=self.observations.get(key)
            if not fresh(s,now*1000) or s['phase']!='qr_unavailable':
                if previous:
                    self.observations.pop(key,None);atomic(self.observation_file,self.observations)
                return False
            if (not previous or previous.get('sessionId')!=s['sessionId']
                or not 0<=now-previous.get('lastObserved',0)<=45):
                previous={'sessionId':s['sessionId'],'firstObserved':now}
            previous['lastObserved']=now;self.observations[key]=previous
            atomic(self.observation_file,self.observations)
            return now-previous['firstObserved']>=120

    def _resolve_qr_warning(self, root, s, qr_message_id):
        if not qr_message_id or s['phase']!='waiting_scan' or not s.get('image'):return
        key=f"{self.cfg['chat_id']}:{s['sessionId']}:qr_unavailable"
        with self.lock:
            item=self.state.get(key)
            if not item or item.get('status')!='sent' or item.get('resolvedAt'):return
            title=f"{s['machine']} · {s['platform']}"
            account=self.cfg.get('machine_accounts',{}).get(s['machine'],{})
            nickname=account.get('platforms',{}).get(s['platform'],{}).get('nickname')
            if nickname:title+=' · '+nickname
            phone=account.get('phone')
            if phone:title+=' · '+phone
            captured=datetime.fromtimestamp(s['image']['capturedAt']/1000,timezone(timedelta(hours=8)))
            text='此后已于'+captured.strftime('%H:%M:%S')+'生成并另发二维码，先前的加载等待已结束。登录请以最新二维码消息为准；这条提醒已解除。'
            message_type=item.get('message_type','post')
            post=notice_content(title,[[{'tag':'text','text':text}]],'resolved',message_type)
            self.lark.call(['im','+messages-edit','--message-id',item['message_id'],'--msg-type',message_type,'--content','-','--as','bot'],stdin=json.dumps(post,ensure_ascii=False))
            item.update(resolvedAt=time.time(),resolvedBy=qr_message_id);atomic(self.state_file,self.state)

    def _invalidate_closed_qr(self, s):
        """Edit the original QR post on closure; don't send another alert."""
        if s['phase']!='cancelled':return
        prefix=f"{self.cfg['chat_id']}:{s['sessionId']}:qr:"
        with self.lock:
            for key,item in self.state.items():
                if not key.startswith(prefix) or item.get('status')!='sent' or item.get('invalidatedAt'):continue
                title=f"{s['machine']} · {s['platform']}"
                account=self.cfg.get('machine_accounts',{}).get(s['machine'],{})
                nickname=account.get('platforms',{}).get(s['platform'],{}).get('nickname')
                if nickname:title+=' · '+nickname
                phone=account.get('phone')
                if phone:title+=' · '+phone
                text='此登录会话已结束，原二维码不再使用，请勿继续扫码。需要登录时，请以该机器、该平台当前会话的新二维码为准。'
                message_type=item.get('message_type','post')
                post=notice_content(title,[[{'tag':'text','text':text}]],'cancelled',message_type)
                self.lark.call(['im','+messages-edit','--message-id',item['message_id'],'--msg-type',message_type,'--content','-','--as','bot'],stdin=json.dumps(post,ensure_ascii=False))
                item['invalidatedAt']=time.time();atomic(self.state_file,self.state)

    def poll_once(self, machine, sessions=None):
        sessions=self.sessions(machine) if sessions is None else sessions
        sessions=sorted(sessions,key=lambda row:({'小红书':0,'抖音':1}.get(row[1]['platform'],2),row[1]['workerId']))
        with self.lock:
            self.attention_snapshots[machine]={'observedAt':time.time(),'sessions':[s for _,s in sessions]}
        for root,s in sessions:
            lock=self.target_lock(machine,s['platform'])
            if not lock.acquire(blocking=False):continue
            try:
                s=with_resume(root,s)
                warning_due=self._qr_warning_due(s)
                if s['phase']=='cancelled':
                    self._invalidate_closed_qr(s)
                    continue
                if s['phase'] in {'waiting_scan','qr_expired'}:
                    if self._qr_due(root,s):self._send(root,s)
                    if s['phase']=='waiting_scan':
                        sent=self.state.get(f"{self.cfg['chat_id']}:{s['sessionId']}:qr:{s['generation']}",{})
                        if sent.get('status')=='sent':self._resolve_qr_warning(root,s,sent.get('message_id'))
                    continue
                if s['phase']=='qr_unavailable' and not warning_due:continue
                if s['phase'] in TERMINAL:
                    # Do not announce historical terminal states on first install.
                    if not any(k.startswith(self.cfg['chat_id']+':'+s['sessionId']+':') for k in self.state):
                        continue
                # Keep intermediate/redundant states available to direct status
                # queries, but do not announce them to the group automatically.
                # with_resume() above may turn verified into an actual task
                # resumption, which remains a useful final notification.
                if s['phase'] in {'opening','verifying','unavailable','cancelled','sms_opening','sms_submitted','sms_requesting'}:
                    continue
                self._send(root,s)
            finally:lock.release()
        return len(sessions)

    def _attention_summary(self, now=None):
        """Use existing polling threads; summarize human work without new actions."""
        if self.cfg.get('operations_reminder_enabled') is not True:return
        now=time.time() if now is None else now
        interval=max(300,min(86400,int(self.cfg.get('operations_reminder_interval_seconds',1800))))
        with self.lock:
            state=self.attention_reminder
            if state.get('chat_id')!=self.cfg['chat_id']:
                state={'chat_id':self.cfg['chat_id'],'nextDue':now+interval}
                self.attention_reminder=state;atomic(self.attention_file,state);return
            if now<state.get('nextDue',now+interval) or now<state.get('retryAt',0):return
            rows=[];observed=set()
            for machine,snapshot in sorted(self.attention_snapshots.items()):
                if not 0<=now-snapshot['observedAt']<=45:continue
                observed.add(machine)
                for s in sorted(snapshot['sessions'],key=lambda s:({'小红书':0,'抖音':1}.get(s['platform'],2),s['workerId'])):
                    if not fresh(s,now*1000):continue
                    phase=s['phase'];action=None
                    command=f"{self.bot_mention} 刷新登录 {machine} {s['platform']}"
                    if phase in {'waiting_scan','qr_expired'}:
                        action='扫码登录：请使用该节点最新二维码；过期可 '+command
                    elif phase=='manual_captcha':action='人工验证码：请在该机器的验证页面完成处理'
                    elif phase=='manual_security':action='安全限制：保留保护，需人工查看该机器页面；不可通过刷新解除'
                    elif phase in {'sms_send_failed','sms_send_unconfirmed','sms_manual','sms_expired'}:
                        action=f"短信验证：未确认可用短信；需要发送时请 {self.bot_mention} 重发验证码 {machine} {s['platform']}"
                    elif phase in {'waiting_sms','sms_rejected'}:
                        if (s.get('smsRequest') or {}).get('accepted') is True:
                            action=f"短信验证：等待人工提供手机收到的验证码，请 {self.bot_mention} 验证码 {machine} {s['platform']} 加上短信数字"
                        else:action='短信验证：尚未确认发送结果，请在该机器查看页面'
                    elif phase=='qr_unavailable':
                        key='|'.join([self.cfg['chat_id'],machine,s['platform'],s['workerId']]);v=self.observations.get(key,{})
                        if v.get('sessionId')==s['sessionId'] and now-v.get('firstObserved',now)>=120:
                            action='登录页面：持续未生成可用二维码，请检查该机器登录窗口'
                    if action:rows.append(f"{machine} · {s['platform']}：{action}")
            if len(observed)<len(self.roots):return
            if not rows:
                state['nextDue']=now+interval;atomic(self.attention_file,state);return
            pending=state.get('pending')
            if not pending:
                pending={'uuid':str(uuid.uuid4()),'firstAttempt':now};state['pending']=pending
            if now-pending['firstAttempt']>=3300:raise RuntimeError('attention_delivery_unconfirmed_requires_review')
            state['retryAt']=now+60;atomic(self.attention_file,state)
            content='\n'.join(rows)+'\n\n二维码按30分钟间隔提醒；手机确认、短信和人工验证处理中不刷新。短信不会由定时提醒自动重发。仅列当前有效会话，未列出不代表节点已核验正常。'
            post=notice_content('集群登录与验证码待处理（30分钟提醒）',[[{'tag':'text','text':content}]],'manual_captcha')
            result=self.lark.call(['im','+messages-send','--chat-id',self.cfg['chat_id'],'--msg-type','interactive','--content','-','--as','bot','--idempotency-key',pending['uuid']],stdin=json.dumps(post,ensure_ascii=False))
            mid=result.get('message_id') or result.get('message',{}).get('message_id')
            if not mid:raise ValueError('attention_delivery_not_confirmed')
            state.update(lastSent=now,nextDue=now+interval,message_id=mid);state.pop('pending',None);state.pop('retryAt',None);atomic(self.attention_file,state)

    def _poll_batch(self, observations):
        """Publish one observation batch in machine order, despite I/O order."""
        for machine in sorted(observations):
            if self.stop.is_set():break
            try:
                result=observations[machine]
                if isinstance(result,Exception):raise result
                count=self.poll_once(machine,sessions=result)
                self.health[machine]={'updated':time.time(),'sessions':count,'error':None}
            except Exception as e:
                self.health[machine]={'updated':time.time(),'error':type(e).__name__}
                LOG.warning('login_bridge_poll machine=%s error=%s',machine,type(e).__name__)
        self._attention_summary()

    def start(self):
        # UNC reads remain independent and bounded to one daemon per machine.
        # A single sender then orders each ready batch; an unreachable machine
        # cannot block the other readers or create more blocked threads.
        condition=threading.Condition();inflight=set();ready={}
        requests={m:threading.Event() for m in self.roots}
        def read_loop(machine):
            while not self.stop.is_set():
                if not requests[machine].wait(.5):continue
                requests[machine].clear()
                if self.stop.is_set():break
                try:result=self.sessions(machine)
                except Exception as e:result=e
                with condition:
                    ready[machine]=result;inflight.discard(machine)
                    condition.notify_all()
        def publish_loop():
            while not self.stop.is_set():
                with condition:
                    for machine in sorted(self.roots):
                        if machine not in inflight and machine not in ready:
                            inflight.add(machine);requests[machine].set()
                    end=time.monotonic()+4
                    while inflight and time.monotonic()<end and not self.stop.is_set():
                        condition.wait(min(.25,max(0,end-time.monotonic())))
                    batch=dict(ready);ready.clear()
                if not self.stop.is_set():self._poll_batch(batch)
                self.stop.wait(8)
        for machine in sorted(self.roots):
            t=threading.Thread(target=read_loop,args=(machine,),name='login-read-'+machine,daemon=True)
            t.start();self.threads.append(t)
        t=threading.Thread(target=publish_loop,name='login-notify-ordered',daemon=True)
        t.start();self.threads.append(t)

    def handle(self, question, event):
        match=PATTERN.fullmatch(question.strip())
        if not match:
            if question.strip().startswith(('刷新登录','登录截图','登录状态')):
                return f'请在 @本机器人 后填写机器和平台，例如：{self.bot_mention} 刷新登录 work01 小红书（也支持“登录截图”“登录状态”）。程序自动匹配对应登录节点，无需填写 worker 编号。'
            return None
        verb,machine,platform,worker=match.groups();machine=machine.lower()
        # A command must be recent human input in the configured group, even on retry.
        if (event.get('sender_type')!='user' or event.get('chat_id')!=self.cfg['chat_id']
            or not any(m.get('id')==self.cfg['bot_open_id'] for m in event.get('mentions',[]))):
            return '仅接受本群人工 @本机器人的直接指令。'
        created=float(event.get('create_time',0));created=created/1000 if created>1e11 else created
        if not -5<=time.time()-created<=120:
            return '这条登录指令已过期，请重新 @本机器人发送。'
        # UNC I/O can stall per machine. Bound the group command's response time;
        # one existing worker per machine prevents unbounded blocked threads.
        result=[]
        def execute():
            try:
                result.append(self._command(verb,machine,platform,worker,event,deadline=command_deadline))
            except Exception as e:
                LOG.warning('login_command_failed machine=%s error=%s',machine,type(e).__name__)
                result.append('登录控制未确认成功，请检查目标机器网络或登录窗口；保护保持原样。')
        target_lock=self.target_lock(machine,platform)
        def wrapped():
            # Passive polling and image delivery briefly own the same node.
            # Queue the human request instead of rejecting that normal overlap.
            if not target_lock.acquire(timeout=12):
                result.append('该平台的上一条登录操作仍未结束，本次未重复刷新；请查询登录状态。');return
            try:execute()
            finally:target_lock.release()
        command_deadline=time.monotonic()+55
        threading.Thread(target=wrapped,daemon=True).start()
        deadline=time.monotonic()+58
        while not result and time.monotonic()<deadline and not self.stop.wait(.2):
            pass
        return result[0] if result else '目标机器响应超时，执行结果尚未确认；请用“登录状态”查询，勿连续刷新。'

    def _command(self, verb, machine, platform, worker, event, deadline=None):
        sessions=[(r,s) for r,s in self.sessions(machine) if s['platform']==platform and (not worker or s['workerId']==worker)
                  and ((fresh(s) and s['phase'] in ACTIVE) or (verb=='登录状态' and s['phase'] in TERMINAL))]
        if len(sessions)!=1:
            return ('找到多个登录会话，请补全 worker 编号。' if len(sessions)>1 else '没有找到该目标的活跃登录恢复会话。不会另开采集浏览器或重启任务。')
        root,s=sessions[0]
        if self.stop.is_set() or (deadline is not None and time.monotonic()>=deadline):
            return '登录请求等待过久已取消，请重新发送。'
        if verb=='登录状态':
            s=with_resume(root,s)
            return f"{machine} {platform}：{LABELS.get(s['phase'],s['phase'])}。"
        cid=str(uuid.uuid5(uuid.NAMESPACE_URL,'login-command:'+event['message_id']))
        now=time.time()*1000
        cmd={'commandId':cid,'sessionId':s['sessionId'],'machine':machine,'platform':platform,'workerId':s['workerId'],
             'action':'refresh' if verb=='刷新登录' else 'screenshot','issuedAt':now,'expiresAt':now+45000}
        existing=None
        try:existing=read_json(root/'command.json')
        except (OSError,ValueError):pass
        pending=(existing and existing.get('sessionId')==s['sessionId']
                 and existing.get('machine')==machine and existing.get('platform')==platform
                 and 0<=now-existing.get('issuedAt',0)<45000 and existing.get('expiresAt',0)>now
                 and (s.get('ack') or {}).get('commandId')!=existing.get('commandId'))
        if pending:
            if existing.get('action')=='refresh' and verb=='刷新登录':cid=existing['commandId']
            else:return '该平台正在完成上一项登录验证，未覆盖原请求或重复刷新。'
        else:atomic(root/'command.json',cmd)
        end=time.monotonic()+38
        while not self.stop.wait(.5) and time.monotonic()<end:
            current=read_json(root/'session.json')
            if current['sessionId']!=s['sessionId']:
                return '登录会话已更换，请重新发送指令。'
            ack=current.get('ack') or {}
            if ack.get('commandId')!=cid:
                continue
            if not ack.get('ok') and ack.get('reason')=='SCAN_CONFIRMATION_PENDING':
                return '当前已扫码，正在等待手机确认；请先在手机完成确认，未刷新页面或发送二维码。'
            if not ack.get('ok'):
                return '未确认二维码刷新成功：'+str(ack.get('reason','未通过核验'))+'。登录与停止保护未解除。'
            if not self._send(root,current,force_key=cid):
                return '当前截图未通过二维码校验，未发送；若已扫码，请先在手机完成确认。'
            return f"{machine} {platform}：二维码已发到群内，请扫码。"
        return '节点尚未确认执行结果，请用“登录状态”查询，勿连续刷新。'
