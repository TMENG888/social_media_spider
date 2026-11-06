import os,sys,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
_test_temp=Path(os.environ.get('LOGIN_TEST_TEMP','E:/Codex/temp/feishu-login-bot-tests'))
_test_temp.mkdir(parents=True,exist_ok=True)
import sys,threading,tempfile,time,json,uuid
from pathlib import Path
from login_bridge import LoginBridge,atomic,read_json
base=Path(str(_test_temp));base.mkdir(parents=True,exist_ok=True)
with tempfile.TemporaryDirectory(dir=base) as d:
 root=Path(d)/'worker/.state/login-bridge';root.mkdir(parents=True)
 cfg={'chat_id':'test','bot_open_id':'bot'};b=LoginBridge(None,cfg,threading.Event(),roots={'work03':str(Path(d))},cache=Path(d)/'cache')
 event={'sender_type':'user','chat_id':'test','mentions':[{'id':'bot'}],'create_time':time.time(),'message_id':'human-test'}
 original=b._command;b._command=lambda *a,**kw:'executed'
 xhs=b.target_lock('work03','小红书');dy=b.target_lock('work03','抖音');dy.acquire()
 assert b.handle('刷新登录 work03 小红书',event)=='executed';dy.release()
 xhs.acquire();threading.Timer(.2,xhs.release).start();started=time.monotonic()
 assert b.handle('刷新登录 work03 小红书',event)=='executed' and time.monotonic()-started>=.15
 # Join an auto-refresh already in flight instead of overwriting its command.
 b._command=original;sid=str(uuid.uuid4());cid=str(uuid.uuid4());now=time.time()*1000
 s={'schema':1,'sessionId':sid,'machine':'work03','platform':'小红书','workerId':'worker-01','phase':'qr_expired','updatedAt':now,'generation':1,'image':None,'ack':None}
 cmd={'commandId':cid,'action':'refresh','sessionId':sid,'machine':'work03','platform':'小红书','workerId':'worker-01','issuedAt':now,'expiresAt':now+45000}
 atomic(root/'session.json',s);atomic(root/'command.json',cmd)
 b.sessions=lambda machine:[(root,read_json(root/'session.json'))]
 sent=[];b._send=lambda r,state,**kw:sent.append(state) or 'om_confirmed'
 def ack():atomic(root/'session.json',{**s,'phase':'waiting_scan','generation':2,'updatedAt':time.time()*1000,'ack':{'commandId':cid,'ok':True}})
 threading.Timer(.1,ack).start()
 result=b._command('刷新登录','work03','小红书',None,event)
 assert '二维码已发' in result and len(sent)==1 and read_json(root/'command.json')==cmd
 print(json.dumps({'humanWaitsForPassivePoll':True,'platformLocksIndependent':True,'pendingRefreshJoined':True,'commandNotOverwritten':True}))
