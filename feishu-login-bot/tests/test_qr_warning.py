import os,sys,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
_test_temp=Path(os.environ.get('LOGIN_TEST_TEMP','E:/Codex/temp/feishu-login-bot-tests'))
_test_temp.mkdir(parents=True,exist_ok=True)
import sys,time,uuid,tempfile,threading,hashlib,json
from pathlib import Path
from unittest.mock import patch
from login_bridge import LoginBridge,atomic
temp=Path(str(_test_temp));temp.mkdir(parents=True,exist_ok=True)
class Lark:
 def __init__(self):self.calls=[]
 def call(self,args,**kw):
  self.calls.append((args,kw))
  if args[:3]==['im','images','create']:return {'image_key':'fixture'}
  if args[1]=='+messages-edit':return {}
  return {'message_id':'om_'+str(len(self.calls))}
with tempfile.TemporaryDirectory(dir=temp) as tmp:
 base=Path(tmp);root=base/'worker/.state/login-bridge';root.mkdir(parents=True)
 l=Lark();b=LoginBridge(l,{'chat_id':'ops_test'},threading.Event(),cache=base/'cache')
 now=time.time();sid=str(uuid.uuid4())
 s={'schema':1,'sessionId':sid,'machine':'work04','platform':'抖音','workerId':'worker-02','hostname':'TEST','phase':'qr_unavailable','updatedAt':now*1000,'createdAt':now*1000,'generation':0,'image':None}
 b.sessions=lambda machine:[(root,s)]
 # Transient loading must send no warning even across multiple observations.
 for elapsed in range(0,120,8):
  s['updatedAt']=(now+elapsed)*1000
  with patch('login_bridge.time.time',return_value=now+elapsed):b.poll_once('work04')
 assert not l.calls
 s['updatedAt']=(now+120)*1000
 with patch('login_bridge.time.time',return_value=now+120):b.poll_once('work04')
 assert len(l.calls)==1 and l.calls[0][0][1]=='+messages-send'
 # Exercise delivery state with a synthetic image and a stub decoder verdict.
 # Real PNG/QR decoding is tested separately; never use a production login QR.
 data=b'\x89PNG\r\n\x1a\n' + b'synthetic-notification-fixture'
 filename='qr-'+sid+'-1.png';(root/filename).write_bytes(data)
 s.update(phase='waiting_scan',generation=1,updatedAt=(now+128)*1000,image={'filename':filename,'sha256':hashlib.sha256(data).hexdigest(),'capturedAt':(now+128)*1000})
 atomic(root/'session.json',s)
 with patch('login_bridge.time.time',return_value=now+128), patch('login_bridge.qr_has_symbol',return_value=True):b.poll_once('work04')
 assert [c[0][1] for c in l.calls].count('+messages-edit')==1
 edit=next(c for c in l.calls if c[0][1]=='+messages-edit');assert edit[0][edit[0].index('--message-id')+1]=='om_1'
 assert '这条提醒已解除' in edit[1]['stdin']
 with patch('login_bridge.time.time',return_value=now+136):b.poll_once('work04')
 assert [c[0][1] for c in l.calls].count('+messages-edit')==1
 # Recovery, a new session or a >45s observation gap starts a fresh grace period.
 s.update(phase='qr_unavailable',updatedAt=(now+140)*1000)
 assert not b._qr_warning_due(s,now+140)
 s['updatedAt']=(now+220)*1000;assert not b._qr_warning_due(s,now+220)
 s['sessionId']=str(uuid.uuid4());s['updatedAt']=(now+228)*1000;assert not b._qr_warning_due(s,now+228)
 # Closing a session replaces its original QR post instead of another send.
 s.update(sessionId=sid,phase='cancelled',updatedAt=(now+230)*1000,image=None)
 before=len(l.calls);b._invalidate_closed_qr(s);assert len(l.calls)==before+1
 assert l.calls[-1][0][1]=='+messages-edit' and '原二维码不再使用' in l.calls[-1][1]['stdin']
 assert 'image_key' not in l.calls[-1][1]['stdin']
 b._invalidate_closed_qr(s);assert len(l.calls)==before+1
 print(json.dumps({'transientWarningSuppressed':True,'persistentWarningAfter120s':True,'previousWarningEditedOnQrReady':True,'editDeduplicated':True,'gapsAndSessionChangesResetGrace':True}))
