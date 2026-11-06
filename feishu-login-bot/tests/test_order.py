import os,sys,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
_test_temp=Path(os.environ.get('LOGIN_TEST_TEMP','E:/Codex/temp/feishu-login-bot-tests'))
_test_temp.mkdir(parents=True,exist_ok=True)
import sys,time,threading,tempfile,json
from pathlib import Path
from login_bridge import LoginBridge
with tempfile.TemporaryDirectory(dir=str(_test_temp)) as t:
 b=LoginBridge(None,{},threading.Event(),cache=Path(t));seen=[]
 b.poll_once=lambda machine,sessions=None:seen.append(machine) or len(sessions)
 b._poll_batch({'work04':[],'work02':OSError('fixture'),'work03':[],'work01':[]})
 assert seen==['work01','work03','work04'] and b.health['work02']['error']=='OSError'
 # Real poll path also fixes platform order within each machine.
 b2=LoginBridge(None,{'chat_id':'fixture'},threading.Event(),cache=Path(t)/'platforms');sent=[]
 b2._send=lambda root,s:sent.append(s['platform'])
 s=lambda p:{'machine':'work03','platform':p,'workerId':'worker-01','sessionId':p,'phase':'manual_captcha','updatedAt':time.time()*1000}
 b2.poll_once('work03',sessions=[(Path(t),s('抖音')),(Path(t),s('小红书'))])
 assert sent==['小红书','抖音']
 # One unresponsive UNC reader must not hold the ready machines indefinitely.
 stop=threading.Event();b3=LoginBridge(None,{},stop,roots={m:t for m in ['work04','work02','work03','work01']},cache=Path(t)/'threads');reads=[];published=[]
 def sessions(machine):
  reads.append(machine)
  if machine=='work02':stop.wait(10)
  else:time.sleep({'work04':.01,'work03':.02,'work01':.05}[machine])
  return []
 b3.sessions=sessions;b3.poll_once=lambda machine,sessions=None:published.append(machine) or 0
 b3.start()
 try:
  end=time.monotonic()+5
  while len(published)<3 and time.monotonic()<end:time.sleep(.05)
  assert published==['work01','work03','work04'],published
  assert reads.count('work02')==1 and len(b3.threads)==5
 finally:
  stop.set()
  for thread in b3.threads:thread.join(1)
 assert all(not thread.is_alive() for thread in b3.threads)
 print(json.dumps({'passed':5,'machineOrder':True,'platformOrder':True,'unreachableMachineDoesNotBlockReadyBatch':True,'boundedReaders':True}))
