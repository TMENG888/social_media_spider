import os,sys,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
_test_temp=Path(os.environ.get('LOGIN_TEST_TEMP','E:/Codex/temp/feishu-login-bot-tests'))
_test_temp.mkdir(parents=True,exist_ok=True)
import sys,json,time,threading,tempfile,uuid,base64,random
from pathlib import Path
from cryptography.hazmat.primitives import hashes,serialization
from cryptography.hazmat.primitives.asymmetric import rsa,padding
import bot
from sms_commands import SmsIntake,sensitive_sms
from login_bridge import LoginBridge,atomic
root=Path(tempfile.mkdtemp(dir=str(_test_temp)));cfg={'chat_id':'group_test','bot_open_id':'bot_test','group_context_enabled':True}
code=str(random.randint(100000,999999));question='验证码 work01 抖音 '+code
event={'message_id':'test_'+str(uuid.uuid4()),'chat_id':cfg['chat_id'],'chat_type':'group','sender_type':'user','sender_id':'human_test','message_type':'text','create_time':str(int(time.time()*1000)),'mentions':[{'id':cfg['bot_open_id'],'key':'@_user_1','name':'机器人'}],'content':'@_user_1 '+question}
passed=0
assert sensitive_sms(question) and sensitive_sms(code) and sensitive_sms('验证码：'+code);passed+=1
assert bot.normalize_group_message(event,cfg,True) is None;passed+=1
historical={**event,'sender':{'sender_type':'user','sender_id':{'open_id':'human_test'}},'content':json.dumps({'text':event['content']},ensure_ascii=False)}
assert bot.normalize_group_message(historical,cfg) is None;passed+=1
store=bot.Store(root/'test.sqlite3');assert store.enqueue(event,'s',question,10)=='sensitive_not_stored';passed+=1
store.remember_group({'message_id':'x','content':question})
with store.connect() as db:assert db.execute('select count(*) from events').fetchone()[0]==0 and db.execute('select count(*) from group_messages').fetchone()[0]==0
passed+=1
class FailStore:
 def remember_group(self,*args):raise AssertionError('OTP reached memory')
 def enqueue(self,*args):raise AssertionError('OTP reached queue')
class Intake:
 calls=0
 def accept(self,text,e):assert text==question;self.calls+=1
b=object.__new__(bot.Bot);b.cfg=cfg;b.store=FailStore();b.sms_intake=Intake();b.ingest(event);assert b.sms_intake.calls==1;passed+=1
# Invalid/malformed sensitive inputs also never fall through to the model.
for t in ['验证码 work05 抖音 '+code,'验证码 work01 抖音 错误'+code,code]:
 e={**event,'content':'@_user_1 '+t};b.sms_intake=type('Discard',(),{'accept':lambda *a:None})();b.ingest(e)
passed+=1
key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
public=key.public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo).decode()
statepath=root/'machine/抖音/worker-03/.state/login-bridge';statepath.mkdir(parents=True)
s={'schema':1,'sessionId':str(uuid.uuid4()),'machine':'work01','platform':'抖音','workerId':'worker-03','updatedAt':time.time()*1000,'phase':'waiting_sms','smsRequest':{'accepted':True},'generation':0,'sms':{'challengeId':str(uuid.uuid4()),'expiresAt':time.time()*1000+300000,'publicKey':public,'attempts':0}}
atomic(statepath/'session.json',s)
stop=threading.Event();bridge=LoginBridge(None,cfg,stop,roots={'work01':str(root/'machine')},cache=root/'cache');intake=SmsIntake(bridge,None,cfg,stop)
def ack():
 for i in range(80):
  if (statepath/'command.json').exists():break
  time.sleep(.05)
 cmd=json.loads((statepath/'command.json').read_text(encoding='utf-8'))
 assert code not in json.dumps(cmd)
 label='|'.join([s['sessionId'],s['machine'],s['platform'],s['workerId'],s['sms']['challengeId']]).encode()
 decoded=key.decrypt(base64.b64decode(cmd['ciphertext']),padding.OAEP(mgf=padding.MGF1(hashes.SHA256()),algorithm=hashes.SHA256(),label=label))
 assert decoded.decode()==code
 current={**s,'updatedAt':time.time()*1000,'phase':'sms_submitted','ack':{'commandId':cmd['commandId'],'ok':True}}
 atomic(statepath/'session.json',current)
t=threading.Thread(target=ack);t.start();answer=intake.execute(question,event);t.join();assert '已提交' in answer and code not in answer;passed+=1
assert '过期' in intake.execute(question,{**event,'create_time':str(int((time.time()-120)*1000))});passed+=1
assert '仅接受' in intake.execute(question,{**event,'sender_type':'app'});passed+=1
assert '仅接受' in intake.execute(question,{**event,'mentions':[]});passed+=1
for p in root.rglob('*'):
 if p.is_file():assert code.encode() not in p.read_bytes()
passed+=1
# Deduplicate the same SMS challenge across notification polls.
class Lark:
 def __init__(self):self.sent=[]
 def call(self,args,**kw):self.sent.append((args,kw));return {'message_id':'test_delivery'}
lark=Lark();bridge.lark=lark;s['updatedAt']=time.time()*1000;atomic(statepath/'session.json',s)
bridge.poll_once('work01');bridge.poll_once('work01');assert len(lark.sent)==1
content=lark.sent[0][1]['stdin'];assert '验证码 work01 抖音' in content and code not in content;passed+=1
atomic(statepath/'session.json',{**s,'phase':'sms_submitted'});bridge.poll_once('work01');assert len(lark.sent)==1;passed+=1
print(json.dumps({'passed':passed,'prePersistenceIntercept':True,'historyExcluded':True,'encryptedTransport':True,'syntheticOnly':True}))

from sms_commands import RESEND
assert sensitive_sms('重发验证码 work01 抖音') and RESEND.fullmatch('重发验证码 work01 抖音');passed+=1
atomic(statepath/'session.json',{**s,'phase':'sms_requesting'});bridge.poll_once('work01');assert len(lark.sent)==1;passed+=1
bad={**s,'smsRequest':None};atomic(statepath/'session.json',bad)
try:bridge._send(statepath,bad)
except ValueError as ex:assert str(ex)=='sms_send_not_confirmed'
else:raise AssertionError('Unconfirmed SMS was advertised')
assert '未确认' in intake.execute(question,event);passed+=1
assert '仅接受' in intake.execute('重发验证码 work01 抖音',{**event,'mentions':[]});passed+=1
assert '过期' in intake.execute('重发验证码 work01 抖音',{**event,'create_time':str(int((time.time()-120)*1000))});passed+=1
assert '未找到' in intake.execute('重发验证码 work02 抖音',event) if 'work02' in bridge.targets else True;passed+=1
print(json.dumps({'passed':passed,'resendDeterministic':True,'unconfirmedNoticeBlocked':True,'syntheticOnly':True}))
