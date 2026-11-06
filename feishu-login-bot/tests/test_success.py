import os,sys,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
_test_temp=Path(os.environ.get('LOGIN_TEST_TEMP','E:/Codex/temp/feishu-login-bot-tests'))
_test_temp.mkdir(parents=True,exist_ok=True)
import sys,time,uuid,threading,tempfile,json
from pathlib import Path
from unittest.mock import patch
from login_bridge import LoginBridge,atomic
class Lark:
 def __init__(self):self.calls=[]
 def call(self,args,**kw):
  self.calls.append((args,kw))
  return {'message_id':'fixture-'+str(len(self.calls))}
with tempfile.TemporaryDirectory(dir=str(_test_temp)) as t:
 root=Path(t)/'worker/.state/login-bridge';root.mkdir(parents=True)
 cfg={'chat_id':'new_ops_group'};l=Lark();b=LoginBridge(l,cfg,threading.Event(),cache=Path(t)/'cache')
 sid=str(uuid.uuid4());now=time.time()*1000
 s={'schema':1,'machine':'work03','platform':'抖音','workerId':'worker-01','hostname':'FIXTURE','sessionId':sid,'phase':'verified','updatedAt':now,'verifiedAt':now,'createdAt':now-10000,'supervisor':{'pid':123,'sessionId':'original'},'generation':1}
 b.sessions=lambda machine:[(root,s)]
 # Suppress historical states when this group never saw the login session.
 b.poll_once('work03');assert not l.calls
 b.state['new_ops_group:'+sid+':qr:1']={'status':'sent','chat_id':'new_ops_group','message_id':'fixture-qr'}
 atomic(root/'session.json',s)
 b.poll_once('work03');b.poll_once('work03')
 assert len(l.calls)==1 and l.calls[0][0][1]=='+messages-send'
 assert l.calls[0][0][l.calls[0][0].index('--chat-id')+1]=='new_ops_group'
 assert '登录核验通过' in l.calls[0][1]['stdin'] and '采集恢复尚待确认' in l.calls[0][1]['stdin']
 resumed={**s,'phase':'resumed','resume':{'keyword':'测试词'}}
 with patch('login_bridge.with_resume',return_value=resumed):
  b.poll_once('work03');b.poll_once('work03')
 assert len(l.calls)==2 and l.calls[1][0][1]=='+messages-edit'
 assert '确认入库' in l.calls[1][1]['stdin']
 assert l.calls[1][0][l.calls[1][0].index('--message-id')+1]=='fixture-1'
 # Wrong-group history does not enable a success push in this group.
 s.update(sessionId=str(uuid.uuid4()),phase='verified')
 b.state['old_group:'+s['sessionId']+':qr:1']={'status':'sent'}
 b.poll_once('work03');assert len(l.calls)==2
 # Verification and SMS-submit intermediate phases remain quiet.
 for phase in ['verifying','sms_submitted','sms_opening','sms_requesting']:
  s['phase']=phase;b.poll_once('work03')
 assert len(l.calls)==2
 print(json.dumps({'passed':7,'newGroupSuccessRouting':True,'successDeduplicated':True,'resumeEditsSameMessage':True,'historicalStatesSuppressed':True}))
