"""OTP commands are intercepted before conversation storage or model routing."""
import json
import re
import threading
import time
import uuid
from pathlib import Path
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

COMMAND=re.compile(r'^验证码\s+(work0[1-4])\s+(小红书|抖音)(?:\s+(worker-0[1-5]))?\s+([0-9]{4,8})$',re.I)
RESEND=re.compile(r'^重发验证码\s+(work0[1-4])\s+(小红书|抖音)(?:\s+(worker-0[1-5]))?$',re.I)
def sensitive_sms(text):
    text=str(text or '')
    text=re.sub(r'<at\b[^>]*>.*?</at>|@_user_\d+', '',text,flags=re.S).strip()
    return bool(re.search(r'验证码\s*(?:work0[1-4]|[：:])',text,re.I)
                or re.fullmatch(r'\s*[0-9]{4,8}\s*',text)
                or re.search(r'(?:验证码|校验码|短信码|动态码)[\s\S]{0,100}?[0-9]{4,8}',text))

def encrypt_code(public_key,session,challenge,code):
    key=serialization.load_pem_public_key(public_key.encode('ascii'))
    if not isinstance(key,rsa.RSAPublicKey) or key.key_size!=2048:raise ValueError('invalid_sms_key')
    label='|'.join([session['sessionId'],session['machine'],session['platform'],session['workerId'],challenge]).encode()
    import base64
    return base64.b64encode(key.encrypt(code.encode('ascii'),padding.OAEP(mgf=padding.MGF1(hashes.SHA256()),algorithm=hashes.SHA256(),label=label))).decode('ascii')

class SmsIntake:
    def __init__(self,bridge,lark,cfg,stop):
        self.bridge,self.lark,self.cfg,self.stop=bridge,lark,cfg,stop
        self.lock=threading.Lock();self.seen={};self.slots=threading.BoundedSemaphore(4)
        self.receipts=bridge.cache/'sms-receipts.json'
        if self.receipts.exists():
            try:self.seen=json.loads(self.receipts.read_text(encoding='utf-8'))
            except (ValueError,OSError):pass
    def accept(self,text,event):
        """Called only after accept_event: the raw message never reaches SQLite."""
        mid=event['message_id'];now=time.time()
        with self.lock:
            if mid in self.seen:return
            self.seen={k:v for k,v in self.seen.items() if v.get('at',0)>now-86400}
            self.seen[mid]={'at':now,'status':'accepted'}
            from login_bridge import atomic
            atomic(self.receipts,self.seen)
        def run():
            answer='验证码处理未确认，请检查对应机器的登录窗口；未解除保护。'
            try:answer=self.execute(text,event)
            except Exception:pass # No exception values may contain the secret.
            if answer is None:
                with self.lock:
                    self.seen[mid]={'at':time.time(),'status':'sent'}
                    from login_bridge import atomic
                    atomic(self.receipts,self.seen)
                return
            try:
                # Do not quote the human's OTP message in a reply/thread.
                result=self.lark.call(['im','+messages-send','--chat-id',self.cfg['chat_id'],'--msg-type','text','--content','-', '--as','bot','--idempotency-key',str(uuid.uuid5(uuid.NAMESPACE_URL,'sms-result:'+mid))],stdin=json.dumps({'text':answer},ensure_ascii=False))
                status='sent' if result.get('message_id') or result.get('message',{}).get('message_id') else 'unconfirmed'
            except Exception:status='unconfirmed'
            with self.lock:
                self.seen[mid]={'at':time.time(),'status':status}
                from login_bridge import atomic
                atomic(self.receipts,self.seen)
        # At most one pending operation per machine, enforced again in execute.
        # Bound total outstanding OTP threads independently from model traffic.
        if not self.slots.acquire(blocking=False):return
        def wrapped():
            try:run()
            finally:self.slots.release()
        threading.Thread(target=wrapped,name='sms-command',daemon=True).start()
    def execute(self,text,event):
        if (event.get('sender_type')!='user' or event.get('chat_id')!=self.cfg['chat_id'] or event.get('chat_type')!='group'
            or not any(x.get('id')==self.cfg['bot_open_id'] for x in event.get('mentions',[]))):
            return '验证码仅接受本群人工 @本机器人的直接指令。'
        created=float(event.get('create_time',0));created=created/1000 if created>1e11 else created
        if not -5<=time.time()-created<=60:return '验证码指令已过期，请在当前验证页面重新提供。'
        resend=RESEND.fullmatch(text.strip())
        if resend:return self.request_sms(*resend.groups(),event)
        m=COMMAND.fullmatch(text.strip())
        if not m:return '请使用：@本机器人 验证码 work01 抖音 加上短信中的数字验证码。'
        machine,platform,worker,code=m.groups();machine=machine.lower()
        lock=self.bridge.target_lock(machine,platform)
        if not lock.acquire(timeout=8):return '该平台的上一条登录操作尚未结束，未重复提交验证码。'
        try:
            from login_bridge import atomic,read_json,fresh
            matches=[(r,s) for r,s in self.bridge.sessions(machine) if s['platform']==platform and (not worker or s['workerId']==worker) and fresh(s) and s['phase'] in {'waiting_sms','sms_rejected'}]
            if len(matches)!=1:return '未找到唯一的待输入短信验证码会话，请先查询该机器的登录状态。'
            root,s=matches[0];ch=s.get('sms') or {};now=time.time()*1000
            if (s.get('smsRequest') or {}).get('accepted') is not True:return '尚未确认本次短信发送被平台受理，请先重发验证码或检查该机器页面。'
            if not (isinstance(ch.get('expiresAt'),(int,float)) and now<ch['expiresAt']<=now+305000 and str(uuid.UUID(ch['challengeId']))==ch['challengeId']):return '当前短信验证已过期，请在对应机器检查登录页面。'
            cid=str(uuid.uuid5(uuid.NAMESPACE_URL,'sms-command:'+event['message_id']))
            ciphertext=encrypt_code(ch['publicKey'],s,ch['challengeId'],code)
            code=None
            command={'commandId':cid,'sessionId':s['sessionId'],'machine':machine,'platform':platform,'workerId':s['workerId'],
                     'action':'submit_sms','challengeId':ch['challengeId'],'ciphertext':ciphertext,'issuedAt':now,'expiresAt':now+45000}
            current=read_json(root/'session.json')
            if not fresh(current) or current['sessionId']!=s['sessionId'] or current.get('sms')!=s.get('sms'):return '登录验证阶段已变化，请查询当前状态。'
            if self.stop.is_set():return '机器人正在更新，请稍后重新提供。'
            atomic(root/'command.json',command)
            end=time.monotonic()+35
            while not self.stop.wait(.5) and time.monotonic()<end:
                current=read_json(root/'session.json')
                if current['sessionId']!=s['sessionId']:return '登录会话已更换，验证码没有用于其他会话。'
                ack=current.get('ack') or {}
                if ack.get('commandId')!=cid:continue
                if not ack.get('ok'):return f'{machine} {platform}：验证码提交未确认，请查看登录状态；保护保留。'
                # Submission is intermediate; actual success follows existing
                # login + original-search verification and resumption receipt.
                return f'{machine} {platform}：验证码已提交，正在核验登录和原检索页；恢复采集后另行通知。'
            return f'{machine} {platform}：验证码执行结果尚未确认，请查询登录状态，勿重复提交。'
        finally:lock.release()

    def request_sms(self,machine,platform,worker,event):
        from login_bridge import atomic,read_json,fresh
        machine=machine.lower()
        lock=self.bridge.target_lock(machine,platform)
        if not lock.acquire(timeout=8):return '该平台的上一条登录操作尚未结束，未重复请求短信。'
        try:
            phases={'waiting_sms','sms_rejected','sms_expired','sms_manual','sms_send_unconfirmed','sms_send_failed'}
            matches=[(r,s) for r,s in self.bridge.sessions(machine) if s['platform']==platform and (not worker or s['workerId']==worker) and fresh(s) and s['phase'] in phases]
            if len(matches)!=1:return '未找到唯一的活跃短信验证页面；不会另开浏览器或改用其他机器。'
            root,s=matches[0];now=time.time()*1000
            cid=str(uuid.uuid5(uuid.NAMESPACE_URL,'resend-sms:'+event['message_id']))
            current=read_json(root/'session.json')
            if not fresh(current) or current['sessionId']!=s['sessionId']:return '登录会话已变化，请查询当前状态。'
            if self.stop.is_set():return '机器人正在更新，请稍后重试。'
            atomic(root/'command.json',{'commandId':cid,'sessionId':s['sessionId'],'machine':machine,'platform':platform,'workerId':s['workerId'],'action':'request_sms','issuedAt':now,'expiresAt':now+45000})
            end=time.monotonic()+35
            while not self.stop.wait(.5) and time.monotonic()<end:
                current=read_json(root/'session.json')
                if current['sessionId']!=s['sessionId']:return '登录会话已更换，未向其他会话重发短信。'
                ack=current.get('ack') or {}
                if ack.get('commandId')!=cid:continue
                if not ack.get('ok'):
                    if ack.get('reason')=='SMS_REQUEST_RATE_LIMIT_60_SECONDS':return '距离上次请求不足60秒，未再次发送短信。'
                    return f'{machine} {platform}：未确认短信重发，请检查该机器的验证页面。'
                if current['phase'] in {'waiting_sms','sms_send_failed','sms_send_unconfirmed'}:
                    if self.bridge._send(root,current):return None
            return f'{machine} {platform}：已请求一次，尚未取得平台受理确认，请勿连续重发。'
        finally:lock.release()
