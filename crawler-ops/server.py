import sys, json, time, threading, secrets, uuid, re, base64
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from concurrent.futures import ThreadPoolExecutor
from settings import *
from adapter import collect, child, timestamp

ORIGIN=f'http://127.0.0.1:{PORT}'
LOCK=threading.RLock();REFRESH=threading.Lock();WAKE=threading.Event()
SNAPSHOT=read_json(OUTPUT/'snapshot.json',{}) or {}
CSRF=secrets.token_urlsafe(32);JOBS={};KEYS={};ACTIVE={};POOL=ThreadPoolExecutor(max_workers=4)

def save_snapshot():
    global SNAPSHOT
    if not REFRESH.acquire(blocking=False):return False
    try:
        value=collect()
        with LOCK:SNAPSHOT=value
        p=OUTPUT/'snapshot.tmp';p.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8');p.replace(OUTPUT/'snapshot.json')
        return True
    except Exception as e:
        with LOCK:SNAPSHOT={**SNAPSHOT,'refreshError':type(e).__name__,'failedAt':time.time()}
        return False
    finally:REFRESH.release()

def loop():
    while True:
        save_snapshot();WAKE.wait(INTERVAL);WAKE.clear()

def audit(job):
    # Fixed fields only. Request bodies, phone numbers and encrypted SMS excluded.
    value={k:job.get(k) for k in ('id','machine','platform','action','createdAt','finishedAt','state','message')}
    with (OUTPUT/'actions.jsonl').open('a',encoding='utf-8') as f:f.write(json.dumps(value,ensure_ascii=False)+'\n')

def verify_dispatch(job):
    """Only observed commit output may become a confirmed collection receipt."""
    from adapter import relay, redis_state
    for _ in range(12):
        time.sleep(5)
        try:
            src=next(s for s in relay.sources(include_channels=False) if s[0]=='小红书')
            r=redis_state(src);m=machine(job['machine'])
            matches=lambda v:v.get('computer','').upper()==m['computer'].upper() and v.get('worker')==worker(m,'xhs')
            fresh=next((h for h in r['workers'] if matches(h) and (timestamp(h.get('lastSeenAt')) or 0)>job['createdAt']),None)
            if job['action']=='open_login':
                s=child('session',data={'machine':job['machine'],'platform':'xhs'},timeout=6)
                if s.get('fresh'):
                    with LOCK:job.update(state='accepted',message='已读到新的有效登录会话，可在验证面板继续处理。',finishedAt=time.time())
                    audit(job);WAKE.set();return
            else:
                committed=any(matches(e) and (timestamp(e.get('committedAt')) or 0)>job['createdAt'] for e in r['events'])
                if fresh and committed:
                    with LOCK:job.update(state='collecting',message='新心跳与后续入库均已核验，采集已恢复。',finishedAt=time.time())
                    audit(job);WAKE.set();return
                if fresh:
                    with LOCK:job.update(state='online',message='监督器已重新上报心跳；实际采集产出仍待核验。安全冷却继续保留。')
        except Exception:continue
    with LOCK:
        job['message']='监督器已上线，尚未观察到新的入库产出；请查看采集或冷却状态。' if job['state']=='online' else '已发出启动请求，尚未取得新心跳或登录会话，需核对原机器。'
        job['finishedAt']=time.time()
    audit(job);WAKE.set()

def execute(job,data):
    key=(job['machine'],job['platform'])
    try:
        if job['action'] in ('recover','open_login'):
            # Recheck live monitoring, not only the displayed five-minute snapshot.
            from adapter import relay, redis_state
            r=next((src for src in relay.sources(include_channels=False) if src[0]=='小红书'),None)
            r=redis_state(r) if r else {}
            m=machine(job['machine']);target=m['computer'].upper()+'/'+worker(m,'xhs')
            if r.get('source')!='ok':result=dict(state='blocked',message='控制通道无法核验，未发送恢复指令。')
            elif any(h.get('target')==target for h in r.get('holds',[])):result=dict(state='blocked',message='存在远程停止保护，未解除保护。')
            elif any(h.get('computer','').upper()==m['computer'].upper() and h.get('worker')==worker(m,'xhs') and (timestamp(h.get('lastSeenAt')) or 0)>=r['sampledAt']-30 for h in r.get('workers',[])):
                result=dict(state='blocked',message='机器刚上报了新心跳，保持当前任务，未重复启动。')
            else:result=child('recover',job['machine'],job['action'],timeout=35)
        else:
            result=child('login',data={**data,'jobId':job['id']},timeout=24)
        with LOCK:
            job.update(state=result.get('state','unconfirmed'),message=result.get('message','未确认结果'),finishedAt=time.time())
        audit(job)
        if job['state']=='dispatched':
            # A dispatch receipt must never become a false "collecting" claim.
            job['message']='启动请求已接收，等待新心跳；采集恢复需看到实际任务活动。' if job['action']=='recover' else '登录窗口启动请求已接收，等待新登录会话；完成登录后可另行恢复采集。'
            threading.Thread(target=verify_dispatch,args=(job,),daemon=True).start()
        WAKE.set()
    except Exception as e:
        with LOCK:job.update(state='unavailable',message='操作未确认：'+type(e).__name__,finishedAt=time.time())
        audit(job)
    finally:
        with LOCK:ACTIVE.pop(key,None)

def submit(data):
    if not isinstance(data,dict):raise ValueError('请求格式不正确')
    if set(data)-{'machine','platform','action','sessionId','idempotencyKey','challengeId','ciphertext','code'}:raise ValueError('包含不支持的字段')
    m=data.get('machine');kind=data.get('platform');action=data.get('action')
    if m not in [x['label'] for x in MACHINES] or kind not in PLATFORMS:raise ValueError('目标机器不存在')
    if action not in ('recover','open_login','refresh_qr','request_sms','submit_sms','login_status'):raise ValueError('不支持此操作')
    if action in ('recover','open_login') and kind!='xhs':raise ValueError('看板尚未开放抖音恢复入口')
    if 'code' in data:
        if action!='submit_sms' or not isinstance(data['code'],str) or not re.fullmatch(r'[0-9]{4,8}',data['code']) or 'ciphertext' in data or not re.fullmatch(r'[a-f0-9-]{36}',str(data.get('challengeId',''))):
            raise ValueError('短信提交格式无效')
    key=data.get('idempotencyKey','')
    if not re.fullmatch(r'[a-f0-9-]{36}',key):raise ValueError('操作标识无效')
    with LOCK:
        if key in KEYS:return JOBS[KEYS[key]]
        if (m,kind) in ACTIVE:raise ValueError('该机器正在处理操作，请等待回执')
        job=dict(id=str(uuid.uuid4()),machine=m,platform=kind,action=action,state='running',createdAt=time.time(),message='正在检查目标及保护状态…')
        JOBS[job['id']]=job;KEYS[key]=job['id'];ACTIVE[(m,kind)]=job['id']
        POOL.submit(execute,job,dict(data))
        return job

class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def send(self,code,body,kind='application/json; charset=utf-8'):
        if isinstance(body,(dict,list)):body=json.dumps(body,ensure_ascii=False).encode('utf-8')
        elif isinstance(body,str):body=body.encode('utf-8')
        self.send_response(code);self.send_header('Content-Type',kind);self.send_header('Content-Length',str(len(body)))
        self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');self.send_header('Referrer-Policy','no-referrer')
        self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        self.end_headers();self.wfile.write(body)
    def valid_host(self):return self.headers.get('Host') in ALLOWED_HOSTS
    def valid_origin(self):return self.valid_host() and self.headers.get('Origin')=='http://'+self.headers.get('Host','')
    def do_GET(self):
        if not self.valid_host():return self.send(403,{'error':'来源地址无效'})
        u=urlparse(self.path)
        if u.path=='/api/health':return self.send(200,{'service':'crawler-ops-independent','pid':__import__('os').getpid(),'interval':INTERVAL,'scheme':'http'})
        if u.path=='/api/state':
            with LOCK:value={**SNAPSHOT,'csrf':CSRF,'refreshing':REFRESH.locked(),'jobs':list(JOBS.values())[-30:],'serverAt':time.time()}
            return self.send(200,value)
        if u.path=='/api/restrictions':
            from restriction_timeline import query
            q=parse_qs(u.query)
            try:
                value=query(days=int(q.get('days',['1'])[0]),platform=q.get('platform',['xhs'])[0],machine=q.get('machine',['all'])[0],page=int(q.get('page',['1'])[0]))
                return self.send(200,value)
            except (ValueError,TypeError):return self.send(400,{'error':'筛选条件无效'})
            except Exception:return self.send(503,{'error':'限制记录暂不可读，请稍后重试'})
        if u.path=='/api/qr':
            q=parse_qs(u.query)
            try:
                data={'machine':q['machine'][0],'platform':q['platform'][0],'sessionId':q['sessionId'][0],'generation':int(q['generation'][0])}
                if data['machine'] not in [m['label'] for m in MACHINES] or data['platform'] not in PLATFORMS:raise ValueError()
                result=child('qr',data=data,timeout=8)
                if result.get('png'):return self.send(200,base64.b64decode(result['png']),'image/png')
            except (KeyError,ValueError):pass
            return self.send(410,{'error':'二维码已失效，请更新面板'})
        if u.path=='/api/session':
            q=parse_qs(u.query)
            try:
                data={'machine':q['machine'][0],'platform':q['platform'][0]}
                if data['machine'] not in [m['label'] for m in MACHINES] or data['platform'] not in PLATFORMS:raise ValueError()
                return self.send(200,child('session',data=data,timeout=8))
            except (KeyError,ValueError):return self.send(400,{'error':'目标无效'})
        files={'/':'index.html','/app.js':'app.js','/style.css':'style.css'}
        if u.path in files:return self.send(200,(BASE/'web'/files[u.path]).read_bytes(),{'/':'text/html; charset=utf-8','/app.js':'application/javascript; charset=utf-8','/style.css':'text/css; charset=utf-8'}[u.path])
        return self.send(404,{'error':'不存在此页面'})
    def do_POST(self):
        if not self.valid_origin() or not secrets.compare_digest(self.headers.get('X-CSRF-Token',''),CSRF):return self.send(403,{'error':'操作来源验证失败，请刷新看板页面'})
        try:
            size=int(self.headers.get('Content-Length','0'))
            if not 0<size<=8192:raise ValueError('请求大小无效')
            if self.headers.get('Content-Type','').split(';')[0]!='application/json':raise ValueError('请求格式无效')
            data=json.loads(self.rfile.read(size))
            if self.path=='/api/refresh':WAKE.set();return self.send(202,{'queued':True})
            if self.path=='/api/action':return self.send(202,submit(data))
            return self.send(404,{'error':'不存在此操作'})
        except (ValueError,TypeError):return self.send(400,{'error':'操作无效、正在处理或目标状态已改变，请更新后重试'})

if __name__=='__main__':
    OUTPUT.mkdir(parents=True,exist_ok=True);TEMP.mkdir(parents=True,exist_ok=True)
    if '--collect-once' in sys.argv:
        print(json.dumps({'ok':save_snapshot(),'snapshot':str(OUTPUT/'snapshot.json')},ensure_ascii=False));sys.exit()
    http=ThreadingHTTPServer((LISTEN_HOST,PORT),Handler)
    threading.Thread(target=loop,daemon=True).start()
    print('Independent crawler dashboard: '+ORIGIN,flush=True)
    print(f'LAN dashboard: http://{LAN_ADDRESS}:{PORT}',flush=True)
    try:http.serve_forever()
    finally:http.server_close()
