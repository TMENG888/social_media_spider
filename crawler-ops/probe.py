"""Bounded child-process adapter. Never prints raw credentials or SMS."""
import sys, json, time, base64, subprocess, hashlib, os, socket
from pathlib import Path
from settings import *
sys.stdout.reconfigure(encoding='utf-8')

def ops_copy(root, kind):
    xhs_login = kind=='login' and root.parent.name == PLATFORMS['xhs']
    filename = ('login-v3.json' if xhs_login else 'login-v2.json') if kind=='login' else kind+'.json'
    value = read_json(root/'.state/ops'/filename, {})
    expected = 'login-sms-recovery-20261116-v3' if xhs_login else 'login-auth-copy-20261111-v2'
    if kind=='login' and value.get('projectionVersion')!=expected:
        return {}
    if value.get('schemaVersion') != 1 or value.get('kind') != kind or value.get('version') != 'ops-state-split-20261111-v1' or not isinstance(value.get('data'), dict):
        return {}
    return value

def session_for(m, kind):
    s = ops_copy(worker_root(m, kind), 'login').get('data', {})
    if s.get('machine') != m['label'] or s.get('platform') != PLATFORMS[kind] or s.get('workerId') != worker(m, kind):
        return {}
    return s


def sms_restart_required(s):
    receipt=s.get('smsRequest') or {}
    return (s.get('platform')=='小红书' and s.get('phase')=='sms_send_failed'
        and receipt.get('source')=='platform_send_response'
        and receipt.get('path')=='/api/redcaptcha/v2/vc/send'
        and receipt.get('restartRequired') is True
        and isinstance(receipt.get('platformCode'), (int, float))
        and receipt['platformCode'] != 0)

def login_error(reason):
    return {
        'SMS_SESSION_RESTART_REQUIRED':'平台要求重新开始登录，请点击“重新开始登录”后重新扫码。',
        'REFRESH_RATE_LIMIT_15_SECONDS':'请等待15秒后再刷新登录二维码。',
        'SMS_REQUEST_RATE_LIMIT_60_SECONDS':'请等待60秒后再获取短信验证码。',
        'SMS_PLATFORM_CODE_EXPIRED':'短信验证码已失效，请重新获取。',
        'SMS_CHALLENGE_EXPIRED_OR_CHANGED':'本地验证会话已更新，请使用当前输入框重新提交。',
        'SMS_SUBMISSION_PENDING':'短信验证码正在核验，请稍等。',
        'QR_REFRESH_NOT_CONFIRMED':'尚未确认生成新二维码，请查看当前登录状态。',
    }.get(reason, '操作未通过：'+str(reason or '未确认')[:90])

def safe_login(s):
    login={k:s.get(k) for k in ('sessionId','updatedAt','phase','generation','workerId','challenge','ack','verifiedAt','feedback','auth','smsReason')}
    login['restartRequired']=sms_restart_required(s)
    auth=s.get('auth') or {}
    if login.get('phase')=='verified' and not (auth.get('version')=='login-proof-20261111-v1' and auth.get('credentialPresent') is True and auth.get('verified') is True):
        login['phase']='verifying'
        login['feedback']={'type':'credential_unconfirmed','message':'等待浏览器登录凭证核验。'}
    sms=s.get('sms') or {}
    login['sms']={k:sms.get(k) for k in ('challengeId','publicKey','expiresAt','attempts')}
    login['hasQr']=s.get('phase')=='waiting_scan' and bool(s.get('image'))
    login['imageGeneration']=s.get('generation')
    login['fresh']=0<=time.time()*1000-float(s.get('updatedAt') or 0)<45000
    return login

def recent_activity(root, state, keyword):
    """Read real operation events; file mtime alone is never a collection signal."""
    result={}
    campaign=state.get('campaign')
    if not campaign or not keyword:return result
    folder_root=root/'runs/redis'/campaign
    if any(c in str(campaign) for c in ('/','\\','..')):return result
    prefix=keyword.replace(' ','_')+'-'
    candidates=[]
    try:
        for topic in folder_root.iterdir():
            if not topic.is_dir():continue
            for folder in topic.iterdir():
                if folder.name.startswith(prefix) and folder.is_dir():
                    candidates.extend((folder/'timing').glob('*.jsonl'))
        if not candidates:return result
        latest=max(candidates,key=lambda p:p.stat().st_mtime)
        with latest.open('rb') as f:
            f.seek(max(0,latest.stat().st_size-262144))
            lines=f.read().decode('utf-8-sig',errors='replace').splitlines()
        for line in lines:
            try:e=json.loads(line)
            except ValueError:continue
            # Ignore heartbeat markers and never include content, URLs or error bodies.
            if e.get('lane')=='foreground' and e.get('event') in ('begin','end','marker'):
                result['foreground']={k:e.get(k) for k in ('at','stage','event','status')}
            if e.get('lane')=='persistence' and e.get('event')=='end' and e.get('status')=='ok':
                result['persistence']={k:e.get(k) for k in ('at','stage','event','status')}
    except OSError:pass
    return result

def files(label):
    m = machine(label)
    rows = []
    for kind, name in PLATFORMS.items():
        root = worker_root(m, kind)
        copies = {kind: ops_copy(root, kind) for kind in ('worker-status', 'supervisor', 'pause', 'cooldown')}
        state = copies['worker-status'].get('data', {})
        sup = copies['supervisor'].get('data', {})
        pause = copies['pause'].get('data', {})
        cool = copies['cooldown'].get('data', {})
        try:
            published = __import__('datetime').datetime.fromisoformat(copies['supervisor'].get('publishedAt', '').replace('Z', '+00:00')).timestamp()
            snapshot_stale = not -5 <= time.time()-published <= 45
        except (ValueError, TypeError):
            snapshot_stale = True
        scope = read_json(root.parent/'common/task-scope.json', {})
        kw = state.get('currentKeyword') or (state.get('tasks') or [{}])[-1].get('keyword')
        manifest = read_json(PACKAGE/name/'common/tasks/redis-tasks.json', {})
        matches = [t for t in manifest.get('tasks', []) if t.get('keyword') == kw and t.get('topic')=='专题一' and t.get('collectComments') is True and t.get('collectionPass')=='articles-comments-20261110-v1']
        date_task=matches[0] if len(matches)==1 else {}
        topics = sorted(set(t['topic'] for t in matches))
        s = session_for(m, kind)
        # The key is public. No account phone, plaintext code or cookies are exposed.
        login = safe_login(s)
        rows.append(dict(machine=label, computer=m['computer'], platform=kind, worker=worker(m,kind),
            keyword=kw, topics=topics, scope=scope.get('allowedTopics',[]),
            state={k:sup.get(k) for k in ('state','updatedAt','resumeAt','supervisorPid')},
            pause={k:pause.get(k) for k in ('phase','resumeAtMs','deadlineAtMs')},
            cooldown={k:cool.get(k) for k in ('active','untilMs','automaticResume','manualRequired')},
            finishedAt=state.get('finishedAt'), login=login,activity=recent_activity(root,state,kw),
            _dateRequest=dict(platform=kind,worker=worker(m,kind),keyword=kw,campaign=state.get('campaign'),topics=topics,projects=PROJECTS,taskId=date_task.get('redisTaskId'),collectionPass=date_task.get('collectionPass'),collectComments=date_task.get('collectComments')),
            fileSource=('stale' if snapshot_stale else 'ok') if state or sup else 'unavailable', snapshotStale=snapshot_stale,
            stops=sorted(set(copies['worker-status'].get('stops', [])+copies['supervisor'].get('stops', [])))))
    requests=[r.pop('_dateRequest') for r in rows]
    requests=[r for r in requests if r.get('keyword') and (r.get('campaign') or r['platform']=='douyin') and r.get('taskId') and '专题一' in r.get('topics',[])]
    if requests:
        # Copy the independent read-only helper only when changed. Keep SSH commands
        # short enough for the Windows command-line limit; never touch crawler state.
        helper=(BASE/'article-dates.mjs').read_bytes()
        digest=hashlib.sha256(helper).hexdigest()[:16]
        filename='ops-article-dates-'+digest+'.mjs'
        target=Path(m['share'])/'采集启动_20261104'/'.updates'/filename
        try:
            target.parent.mkdir(exist_ok=True)
            if not target.exists():target.write_bytes(helper)
        except OSError as e:
            for row in rows:row['dateProgress']={'source':'unavailable','errorType':type(e).__name__}
            return rows
        targets=base64.b64encode(json.dumps(requests,ensure_ascii=False).encode('utf-8')).decode('ascii')
        script="$cfg=Get-Content -LiteralPath '"+m['startupRoot']+"\\machine.json' -Raw -Encoding UTF8|ConvertFrom-Json;"
        script+="if($cfg.computer -ne $env:COMPUTERNAME){throw 'DATE_MACHINE_MISMATCH'};$node=Join-Path $cfg.packageRoot '小红书\\common\\runtime\\node\\node.exe';"
        script+="& $node '"+m['startupRoot']+"\\.updates\\"+filename+"' '"+targets+"' $cfg.packageRoot"
        try:dates=remote(m,script,timeout=16)
        except (OSError,subprocess.TimeoutExpired):dates=[]
        for row in rows:
            row['dateProgress']=next((d for d in dates if isinstance(d,dict) and d.get('platform')==row['platform'] and d.get('keyword')==row.get('keyword')),{'source':'unavailable'}) if isinstance(dates,list) else {'source':'unavailable','errorType':dates.get('state','DATE_REMOTE_UNAVAILABLE') if isinstance(dates,dict) else 'DATE_REMOTE_UNAVAILABLE'}
    return rows

def remote(m, script, timeout=28):
    code="$ErrorActionPreference='Stop';$ProgressPreference='SilentlyContinue';[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false);"+script
    enc=base64.b64encode(code.encode('utf-16le')).decode()
    try:host=socket.gethostbyname(m['computer'])
    except socket.gaierror:
        # Configured fallback; remote identity checks remain required.
        host=m.get('address')
        if not host: raise OSError('REMOTE_ADDRESS_UNAVAILABLE')
    p=subprocess.run(['ssh','-F',str(SSH_CONFIG),'-o','HostName='+host,'-o','HostKeyAlias='+m['computer'].lower(),m['alias'],'powershell.exe -NoProfile -ExecutionPolicy Bypass -EncodedCommand '+enc],capture_output=True,timeout=timeout)
    if p.returncode:
        return {'state':'unavailable','message':'远程启动通道不可用；未启动任何任务。请在机器原桌面运行小红书启动入口。'}
    try:return json.loads(p.stdout.decode('utf-8-sig'))
    except ValueError:return {'state':'unconfirmed','message':'远程回执无法解析，请核对机器状态。'}

def recover(label, action):
    m=machine(label)
    # Only XHS can be started here. All checks execute on the target computer.
    prefix="$StartupRoot='"+m['startupRoot']+"';$cfg=Get-Content -LiteralPath (Join-Path $StartupRoot 'machine.json') -Raw -Encoding utf8|ConvertFrom-Json;"
    prefix+="if($env:COMPUTERNAME -ne '"+m['computer']+"' -or $cfg.computer -ne $env:COMPUTERNAME -or $cfg.xhsWorker -ne '"+worker(m,'xhs')+"'){throw 'IDENTITY_MISMATCH'};"
    checks=r'''
$root=Join-Path $cfg.packageRoot '小红书';$w=Join-Path $root $cfg.xhsWorker
foreach($dir in Get-ChildItem -LiteralPath $root -Directory -Filter 'worker-*'){
 foreach($n in 'worker.lock','monitor-supervisor.lock'){
  $f=Join-Path $dir.FullName ('.state\'+$n)
  if(Test-Path -LiteralPath $f){try{$h=[IO.File]::Open($f,'Open','ReadWrite','None');$h.Dispose()}catch{[pscustomobject]@{state='blocked';message='已有采集或监督进程持有运行锁，未重复启动。'}|ConvertTo-Json -Compress;exit}}
 }
 foreach($n in 'supervisor.stop','stop.requested','remote-control-recovery.lock'){
  if(Test-Path -LiteralPath (Join-Path $dir.FullName ('.state\'+$n))){[pscustomobject]@{state='blocked';message='存在停止或控制保护标记，保留保护，请先核对原因。'}|ConvertTo-Json -Compress;exit}
 }
 $f=Join-Path $dir.FullName '.state\monitor-supervisor.json'
 if(Test-Path -LiteralPath $f){$s=Get-Content -LiteralPath $f -Raw -Encoding utf8|ConvertFrom-Json
  if($s.supervisorPid){$p=Get-Process -Id $s.supervisorPid -ErrorAction SilentlyContinue;if($p){[pscustomobject]@{state='blocked';message='监督进程仍存在，需先核实心跳；未重复启动。'}|ConvertTo-Json -Compress;exit}}
 }
}
foreach($n in 'xhs-open-login.request.json','xhs-reset-login.request.json'){
 if(Test-Path -LiteralPath (Join-Path $StartupRoot $n)){[pscustomobject]@{state='blocked';message='已有登录操作请求，等待原操作处理。'}|ConvertTo-Json -Compress;exit}
}
$service=New-Object -ComObject Schedule.Service;$service.Connect();$t=$service.GetFolder('\').GetTask('Codex-Collector-XHS-20261104')
$a=$t.Definition.Actions.Item(1)
if($t.State -eq 4){[pscustomobject]@{state='blocked';message='启动计划任务仍在运行，未重复启动。'}|ConvertTo-Json -Compress;exit}
if($a.Path -notmatch 'powershell(?:\.exe)?$' -or $a.Arguments -notlike ('*"'+$StartupRoot+'\start-platforms.ps1"*') -or $a.Arguments -notmatch '-Platform xhs' -or $t.Definition.Principal.LogonType -ne 3 -or $t.Definition.Principal.UserId -ne $cfg.desktopUser){throw 'TASK_CONTRACT_MISMATCH'}
'''
    if action=='open_login':
        checks+=r'''
$c=Join-Path $w '.state\rate-limit-cooldown.json'
if(Test-Path -LiteralPath $c){$v=Get-Content -LiteralPath $c -Raw -Encoding utf8|ConvertFrom-Json;if($v.active -and $v.untilMs -gt [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()){[pscustomobject]@{state='blocked';message='仍在安全冷却，保留等待，不打开新登录页面。'}|ConvertTo-Json -Compress;exit}}
$r=@{version='20261104-login-only-v1';requestId=[guid]::NewGuid().ToString();computer=$env:COMPUTERNAME;platform='xhs';worker=$cfg.xhsWorker;expiresAt=[DateTimeOffset]::UtcNow.AddMinutes(2).ToString('o');requireManualConfirmation=$false;resumeAfterVerification=$false}
$file=Join-Path $StartupRoot 'xhs-open-login.request.json'
[IO.File]::WriteAllText($file,($r|ConvertTo-Json),[Text.UTF8Encoding]::new($false))
'''
    checks+="$null=$t.Run($null);[pscustomobject]@{state='dispatched';message='原桌面启动任务已接收；等待新心跳和实际采集核验。安全冷却继续保留。'}|ConvertTo-Json -Compress"
    return remote(m,prefix+checks)

def encode_sms_for_bridge(code, sms, session):
    # The browser uses HTTP by user request. Only the existing node-command
    # protocol retains RSA; no plaintext is written into command files.
    from cryptography.hazmat.primitives import serialization, hashes
    from cryptography.hazmat.primitives.asymmetric import padding
    key=serialization.load_pem_public_key(sms['publicKey'].encode('ascii'))
    label='|'.join([session['sessionId'],session['machine'],session['platform'],session['workerId'],sms['challengeId']]).encode('utf-8')
    return base64.b64encode(key.encrypt(code.encode('ascii'),padding.OAEP(mgf=padding.MGF1(hashes.SHA256()),algorithm=hashes.SHA256(),label=label))).decode('ascii')

def login_command(data):
    m=machine(data['machine']);kind=data['platform'];action=data['action']
    s=session_for(m,kind);now=int(time.time()*1000)
    if not s or s.get('sessionId')!=data.get('sessionId') or not 0<=now-float(s.get('updatedAt') or 0)<45000:
        return dict(state='blocked',message='登录会话已过期或改变，请更新面板后重试。')
    if s.get('phase') in ('verified','cancelled','unavailable'):
        return dict(state='blocked',message='当前会话不接受登录操作。')
    allowed={'refresh_qr':'refresh','request_sms':'request_sms','submit_sms':'submit_sms','login_status':'status'}
    c=dict(commandId=data['jobId'],sessionId=s['sessionId'],machine=m['label'],platform=PLATFORMS[kind],workerId=worker(m,kind),action=allowed[action],issuedAt=now,expiresAt=now+60000)
    if action=='refresh_qr' and s.get('phase') not in ('waiting_scan','qr_expired','qr_rejected','qr_unavailable') and not (kind=='xhs' and sms_restart_required(s)):
        return dict(state='blocked',message='当前正在验证或等待手机确认，不能刷新登录页。')
    if action in ('request_sms','submit_sms') and sms_restart_required(s):
        return dict(state='blocked',message=login_error('SMS_SESSION_RESTART_REQUIRED'))
    if action=='submit_sms':
        sms=s.get('sms') or {}
        if data.get('challengeId')!=sms.get('challengeId') or (sms.get('expiresAt') or 0)<=now:
            return dict(state='blocked',message='短信验证已过期，请更新当前会话。')
        import re
        if 'code' in data:
            code=data.pop('code')
            if not isinstance(code,str) or not re.fullmatch(r'[0-9]{4,8}',code) or s.get('phase') not in ('waiting_sms','sms_rejected'):
                return dict(state='blocked',message='当前会话不接受短信验证码。')
            try:data['ciphertext']=encode_sms_for_bridge(code,sms,s)
            except Exception:return dict(state='blocked',message='验证码转交失败，请更新会话后重试。')
            finally:code=None
        if not re.fullmatch(r'[A-Za-z0-9+/]{340,344}={0,2}',data.get('ciphertext','')):
            return dict(state='blocked',message='短信加密数据格式无效。')
        c.update(challengeId=data['challengeId'],ciphertext=data['ciphertext'])
    root=worker_root(m,kind)/'.state/login-bridge'
    old=read_json(root/'command.json',{})
    if old.get('expiresAt',0)>now and (s.get('ack') or {}).get('commandId')!=old.get('commandId'):
        return dict(state='blocked',message='该机器正在处理另一条登录指令，请稍后再试。')
    temp=root/('dashboard-'+data['jobId']+'.tmp')
    temp.write_text(json.dumps(c,ensure_ascii=False),encoding='utf-8');os.replace(temp,root/'command.json')
    for _ in range(24):
        time.sleep(.6);latest=session_for(m,kind)
        if latest.get('sessionId')!=s['sessionId']:
            return dict(state='unconfirmed',message='登录会话已切换，请查看新会话状态。')
        ack=latest.get('ack') or {}
        if ack.get('commandId')==c['commandId']:
            return dict(state='accepted' if ack.get('ok') else 'blocked',message='操作已提交，正在核验平台结果。' if ack.get('ok') else login_error(ack.get('reason')))
    return dict(state='unconfirmed',message='指令已写入，尚未取得浏览器执行回执；请勿连续提交。')

def qr(data):
    m=machine(data['machine']);kind=data['platform'];s=session_for(m,kind)
    if s.get('sessionId')!=data.get('sessionId') or s.get('generation')!=data.get('generation') or not 0<=time.time()*1000-float(s.get('updatedAt') or 0)<45000 or s.get('phase')!='waiting_scan':
        return {'error':'二维码会话已失效'}
    img=s.get('image') or {};name=img.get('filename','')
    if name!=f"qr-{s['sessionId']}-{s['generation']}.png":return {'error':'二维码不可用'}
    b=(worker_root(m,kind)/'.state/login-bridge'/name).read_bytes()
    if len(b)>2_000_000 or hashlib.sha256(b).hexdigest()!=img.get('sha256'):return {'error':'二维码核验失败'}
    return {'png':base64.b64encode(b).decode()}

if __name__=='__main__':
    try:
        if sys.argv[1]=='files':result=files(sys.argv[2])
        elif sys.argv[1]=='restrictions':
            from restriction_timeline import collect_files
            result=collect_files(sys.argv[2])
        elif sys.argv[1]=='recover':result=recover(sys.argv[2],sys.argv[3])
        elif sys.argv[1]=='login':result=login_command(json.loads(sys.stdin.read()))
        elif sys.argv[1]=='qr':result=qr(json.loads(sys.stdin.read()))
        elif sys.argv[1]=='session':
            d=json.loads(sys.stdin.read());result=safe_login(session_for(machine(d['machine']),d['platform']))
        else:raise ValueError('UNKNOWN_ACTION')
        print(json.dumps(result,ensure_ascii=False))
    except Exception as e:
        print(json.dumps({'state':'unavailable','message':'读取或执行失败：'+type(e).__name__},ensure_ascii=False))
