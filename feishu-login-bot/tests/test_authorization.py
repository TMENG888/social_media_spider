import os,sys,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
_test_temp=Path(os.environ.get('LOGIN_TEST_TEMP','E:/Codex/temp/feishu-login-bot-tests'))
_test_temp.mkdir(parents=True,exist_ok=True)
import sys,tempfile,time,threading,hashlib,json
from pathlib import Path
from login_bridge import LoginBridge,atomic
tmp=Path(str(_test_temp));tmp.mkdir(parents=True,exist_ok=True)
with tempfile.TemporaryDirectory(dir=tmp) as d:
 r=Path(d)/'worker/.state/login-bridge';r.mkdir(parents=True)
 b=LoginBridge(None,{'chat_id':'test'},threading.Event(),cache=Path(d)/'cache')
 now=time.time()*1000
 s={'sessionId':'sample','pid':1234,'machine':'work03','platform':'小红书','workerId':'worker-01','hostname':'TEST_HOST','updatedAt':now}
 hashes={}
 for n in ['supervisor.stop','stop.requested']:
  (r.parent/n).write_text('manual stop',encoding='utf-8');hashes[n]=hashlib.sha256((r.parent/n).read_bytes()).hexdigest()
 assert not b._paused_login_authorized(r,s,now)
 a={'schema':1,'purpose':'login_only_paused',**s,'createdAt':now-100,'expiresAt':now+3600000,'stopHashes':hashes}
 atomic(r/'login-only-authorized.json',a);assert b._paused_login_authorized(r,s,now)
 atomic(r/'login-only-authorized.json',{**a,'purpose':'login_before_authorized_restart'});assert b._paused_login_authorized(r,s,now)
 atomic(r/'login-only-authorized.json',{**a,'purpose':'arbitrary'});assert not b._paused_login_authorized(r,s,now)
 atomic(r/'login-only-authorized.json',a)
 for k in ['sessionId','pid','machine','platform','workerId','hostname']:
  assert not b._paused_login_authorized(r,{**s,k:'different'},now)
 assert not b._paused_login_authorized(r,s,now+3600000)
 assert not b._paused_login_authorized(r,{**s,'updatedAt':now-46000},now)
 (r.parent/'stop.requested').write_text('changed',encoding='utf-8');assert not b._paused_login_authorized(r,s,now)
 print(json.dumps({'checks':13,'pausedWindowBounded':True,'restartLoginBounded':True,'targetSessionBound':True,'stopChangesRejected':True}))
