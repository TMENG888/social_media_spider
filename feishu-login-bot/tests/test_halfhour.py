import os,sys,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
_test_temp=Path(os.environ.get('LOGIN_TEST_TEMP','E:/Codex/temp/feishu-login-bot-tests'))
_test_temp.mkdir(parents=True,exist_ok=True)
import sys,tempfile,time,threading,json,uuid
from pathlib import Path
from login_bridge import LoginBridge,atomic
temp=Path(str(_test_temp));temp.mkdir(parents=True,exist_ok=True)
class Lark:
 def __init__(self):self.calls=[]
 def call(self,args,**kw):self.calls.append((args,kw));return {'message_id':'om_summary'}
with tempfile.TemporaryDirectory(dir=temp) as d:
 p=Path(d);root=p/'worker/.state/login-bridge';root.mkdir(parents=True);now=time.time()
 cfg={'chat_id':'ops_test','operations_reminder_enabled':True,'operations_reminder_interval_seconds':1800,'qr_reminder_interval_seconds':1800}
 l=Lark();b=LoginBridge(l,cfg,threading.Event(),roots={m:str(p/m) for m in ['work01','work02','work03','work04']},cache=p/'cache')
 def session(machine,platform,phase,t):return {'schema':1,'sessionId':str(uuid.uuid4()),'machine':machine,'platform':platform,'workerId':'worker-01','phase':phase,'updatedAt':t*1000}
 def snapshots(t):
  phases=[('work01','抖音','manual_captcha'),('work02','小红书','verifying'),('work03','小红书','waiting_scan'),('work04','抖音','sms_send_unconfirmed')]
  b.attention_snapshots={m:{'observedAt':t,'sessions':[session(m,pl,ph,t)]} for m,pl,ph in phases}
 snapshots(now);b._attention_summary(now);assert not l.calls
 snapshots(now+1799);b._attention_summary(now+1799);assert not l.calls
 snapshots(now+1800);b._attention_summary(now+1800);assert len(l.calls)==1
 content=l.calls[0][1]['stdin'];assert '人工验证码' in content and '扫码登录' in content and '重发验证码 work04 抖音' in content
 assert 'work02 · 小红书' not in content and '短信不会由定时提醒自动重发' in content
 assert l.calls[0][0][1]=='+messages-send'
 snapshots(now+1808);b._attention_summary(now+1808);assert len(l.calls)==1
 # Persistence prevents another summary when the bot restarts.
 again=LoginBridge(l,cfg,threading.Event(),roots=b.roots,cache=b.cache);again.attention_snapshots=b.attention_snapshots;again._attention_summary(now+1808);assert len(l.calls)==1
 # QR cadence changes to 30 minutes; observations remain every eight seconds.
 s=session('work03','小红书','waiting_scan',now);s.update(createdAt=now*1000,generation=1,image={'capturedAt':now*1000})
 b.state[cfg['chat_id']+':'+s['sessionId']+':qr:1']={'status':'sent','sentAt':now}
 for delta in [600,1799]:
  v={**s,'phase':'qr_expired','updatedAt':(now+delta)*1000};atomic(root/'session.json',v);assert not b._qr_due(root,v,now+delta);assert not (root/'command.json').exists()
 v={**s,'phase':'qr_expired','updatedAt':(now+1800)*1000};atomic(root/'session.json',v);assert not b._qr_due(root,v,now+1800)
 assert json.loads((root/'command.json').read_text(encoding='utf-8'))['action']=='refresh'
 print(json.dumps({'summaryAfter1800s':True,'noReminderAt600s':True,'qrRefreshAfter1800s':True,'smsNotSentByTimer':True,'verificationNotRefreshed':True,'restartScheduleRetained':True}))
