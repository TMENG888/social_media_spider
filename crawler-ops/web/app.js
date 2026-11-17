'use strict';
const $=s=>document.querySelector(s);let state={},filter='xhs',current=null,busy=false,toastTimer,pendingOperation=null;
let restrictionPage=1,restrictionPages=1,restrictionRequest=0;
const visibleWorks=new Set(['work01','work02','work03','work04']);let keywordPage=1;const keywordPageSize=5;
const views={restrictions:['限制时间线',''],machines:['机器运行','查看当前采集位置，处理掉线和登录验证。'],verification:['登录与验证',''],receipts:['操作回执',''],definitions:['统计口径','']};
function applyView(){const view=location.hash.slice(1) in views?location.hash.slice(1):'machines';document.querySelectorAll('.sidebar nav a').forEach(a=>{const selected=a.hash==='#'+view;a.classList.toggle('selected',selected);if(selected)a.setAttribute('aria-current','page');else a.removeAttribute('aria-current')});$('#overview').hidden=view!=='machines';$('#keywords').hidden=!['machines','keywords'].includes(view);$('#machines').hidden=view!=='machines';$('#verification').hidden=view!=='verification';$('.workspace').hidden=!['machines','verification'].includes(view);$('#restrictions').hidden=view!=='restrictions';$('#receipts').hidden=view!=='receipts';$('#definitions').hidden=view!=='definitions';if(view==='definitions')$('#definitions').open=true;$('.platform-switch').hidden=!['machines','verification','keywords','restrictions'].includes(view);$('h1').textContent=views[view][0];$('.top p').textContent=views[view][1];$('.top p').hidden=!views[view][1];$('.breadcrumb').textContent='采集集群 / '+views[view][0];window.scrollTo(0,0);if(view==='restrictions')loadRestrictions()}
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const num=n=>n===null||n===undefined?'—':Number(n).toLocaleString('zh-CN');
const time=v=>{if(!v)return '未确认';let d=new Date(typeof v==='number'?(v>1e12?v:v*1000):v);return isNaN(d)?'未确认':d.toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit',hour12:false})};
const short=v=>time(v).split(' ').pop();
const published=v=>typeof v==='string'&&/^\d{4}-\d{2}-\d{2}/.test(v)?v.replace('T',' ').slice(0,19):'—';
function articleDates(r){const d=r.dateProgress?.keyword===r.keyword?r.dateProgress||{}:{};return `<div class="article-dates"><div class="date-line"><span>最近采到</span><time>${esc(published(d.latestCollectedPublishedAt))}</time></div><div class="date-line"><span>入库最早</span><time>${esc(published(d.earliestImportedPublishedAt))}</time></div></div>`;}
const names={xhs:'小红书',douyin:'抖音'};
const actions={recover:'恢复采集',open_login:'打开登录窗口',refresh_qr:'刷新二维码',request_sms:'获取／重发短信',submit_sms:'提交验证码',login_status:'核验登录'};
function operationId(){const b=crypto.getRandomValues(new Uint8Array(16));b[6]=(b[6]&15)|64;b[8]=(b[8]&63)|128;const h=Array.from(b,x=>x.toString(16).padStart(2,'0')).join('');return `${h.slice(0,8)}-${h.slice(8,12)}-${h.slice(12,16)}-${h.slice(16,20)}-${h.slice(20)}`}
const jobStates={running:'执行中',dispatched:'已发送，待核验',online:'监督器已上线',collecting:'已恢复并核验入库',accepted:'操作已执行',blocked:'已阻止',unavailable:'通道不可用',unconfirmed:'结果待核实'};
function toast(text){$('#toast').textContent=text;$('#toast').hidden=false;clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('#toast').hidden=true,6500)}
function phase(s){if(s?.restartRequired)return '需要重新开始登录';const p=s?.phase||'';if(p==='verified')return s.auth?.version==='login-proof-20261111-v1'&&s.auth?.credentialPresent&&s.auth?.verified?'登录凭证已核验，登录成功':'等待浏览器登录凭证核验';if(p==='sms_expired')return s.feedback?.type==='sms_code_expired'?'短信验证码已失效':'本地验证会话已到期';if(p==='verifying')return '等待手机确认／登录凭证核验';if(p==='manual_captcha'){const t=s.challenge?.type;return t==='slider'?'需要拖动滑块验证':/click|select|point/.test(t||'')?'需要点选图片验证':'需要人工验证码验证'}return ({waiting_scan:'等待扫码登录',qr_expired:'二维码已失效',qr_rejected:'扫码登录未通过',waiting_sms:'等待短信验证码',sms_rejected:'短信验证码错误',sms_expired:'短信验证码已失效',sms_submitted:'短信已提交，等待平台验证',sms_requesting:'正在请求短信',sms_send_failed:'短信发送失败',sms_send_unconfirmed:'短信发送结果待确认',sms_opening:'正在打开短信验证',sms_manual:'等待人工短信验证',manual_security:'平台安全验证',manual_gateway:'页面访问验证',opening:'正在打开登录页',qr_unavailable:'等待生成二维码',cancelled:'会话已结束',unavailable:'会话不可用'})[p]||'登录状态待核实'}
function loginActionError(reason){return ({SMS_SESSION_RESTART_REQUIRED:'平台要求重新开始登录，请点击“重新开始登录”后重新扫码。',REFRESH_RATE_LIMIT_15_SECONDS:'请等待15秒后再刷新登录二维码。',SMS_REQUEST_RATE_LIMIT_60_SECONDS:'请等待60秒后再获取短信验证码。',SMS_PLATFORM_CODE_EXPIRED:'短信验证码已失效，请重新获取。',SMS_CHALLENGE_EXPIRED_OR_CHANGED:'本地验证会话已更新，请使用当前输入框重新提交。',SMS_SUBMISSION_PENDING:'短信验证码正在核验，请稍等。',QR_REFRESH_NOT_CONFIRMED:'尚未确认生成新二维码，请查看当前登录状态。'})[reason]||'操作未通过：'+String(reason||'未确认');}
function dialogFeedback(s){if(s?.restartRequired)return '平台已拒绝本次短信验证，请重新开始登录并扫码。';if(s?.feedback?.message)return s.feedback.message;return ({sms_rejected:'短信验证码错误，请重新输入。',sms_expired:s?.feedback?.type==='sms_code_expired'?'短信验证码已失效，请重新获取。':'本地验证会话已到期，请更新当前会话。',qr_expired:'二维码已失效，请刷新二维码。',qr_rejected:'扫码登录未通过，请重新扫码。',sms_submitted:'短信已提交；待浏览器登录凭证核验通过后，才算登录成功。'})[s?.phase]||'';}

function activeLogin(r){return r.login?.fresh&&r.login.sessionId&&!['verified','cancelled','unavailable'].includes(r.login.phase)}
function color(r){return ({collecting:'green',background:'blue',resting:'blue',cooldown:'blue',verification:'amber',stale:'amber',waiting:'blue'})[r.status]||'gray'}
async function post(path,data){const r=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':state.csrf},body:JSON.stringify(data)});const v=await r.json();if(!r.ok)throw Error(v.error||'操作未确认');return v}
async function load(){try{const r=await fetch('/api/state');if(!r.ok)throw Error();const next=await r.json();if(current){const old=state.machines?.find(x=>x.id===current)?.login;const row=next.machines?.find(x=>x.id===current);if(row&&old?.updatedAt>Number(row.login?.updatedAt||0))row.login=old;}state=next;render();}catch{$('#notice').hidden=false;$('#notice').textContent='无法连接本机看板服务，当前显示的数据可能已过期。请检查看板启动脚本。'}}
function render(){
 if(location.hash==='#restrictions')loadRestrictions();
 renderKeywords();
 const rows=(state.machines||[]).filter(r=>visibleWorks.has(r.machine));const platformRows=rows.filter(r=>r.platform===filter);const age=Date.now()/1000-(state.sampledAt||0);
 $('#sampled').textContent=state.sampledAt?'上次采样 '+time(state.sampledAt)+'（北京）':'首次采样中，请稍候…';
 $('#today').textContent=new Date().toLocaleDateString('zh-CN',{timeZone:'Asia/Shanghai'});
 const warns=[...(state.warnings||[])];if(age>360&&state.sampledAt)warns.push('当前采样已过期，请更新后再判断机器状态。');if(state.refreshError)warns.push('本轮更新失败，保留上一份采样。');
 $('#notice').hidden=!warns.length;$('#notice').textContent=warns.join(' ');
 $('#refresh').disabled=!!state.refreshing;$('#refresh').firstChild.textContent=state.refreshing?'更新中…':'立即更新';
 const db=state.database||{};
 $('#summary').innerHTML=(state.platforms||[]).filter(p=>p.key===filter).map(p=>{const hour=db.hour?.values?.[p.name]?.comments;const day=db.day?.values?.[p.name]?.comments;return `<div class="summary-row"><div class="platform-title"><span class="platform-icon ${p.key==='douyin'?'dy':''}">${p.key==='xhs'?'红':'抖'}</span>${esc(p.name)}</div><div class="summary-number" data-label="近1小时新增帖子">${num(p.output?.hour)}<small>篇</small></div><div class="summary-number" data-label="今日新增帖子">${num(p.output?.day)}<small>篇</small></div><div class="summary-number" data-label="近1小时评论净增">${num(hour)}<small>条</small></div><div class="summary-number" data-label="今日评论净增">${num(day)}<small>条</small></div></div>`}).join('')||'<div class="empty">正在读取入库流水…</div>';
 const online=platformRows.filter(r=>['collecting','background','verification','resting','cooldown','waiting'].includes(r.status)).length;$('#onlineCount').textContent=`${online} / ${platformRows.length||4} 节点有运行证据`;
 $('#machineTable').innerHTML=[filter].map(kind=>{const rr=rows.filter(r=>r.platform===kind);return `<div class="group-title"><b>${names[kind]}</b><span>work01—work04 · ${rr.length} 个节点</span></div><div class="machine-head"><span>机器</span><span>采集状态／活动</span><span>当前专题／检索词</span><span title="最近采到：最后保存的一篇文章的发布日期。入库最早：仅新版专题一文章＋评论批次；本批次文章经数据库核验后的最早发布日期。">文章发布日期</span><span>近1h / 今日帖子</span><span>操作</span></div>${rr.map(r=>{
 const heartbeat=r.heartbeatAt?time(r.heartbeatAt):'未读到';const resume=r.resumeAt||r.pause?.resumeAtMs||(r.cooldown?.active?r.cooldown.untilMs:null);
 let op=activeLogin(r)?`<button class="button" data-login="${r.id}">处理登录</button>`:r.canRecover?`<button class="button" data-action="recover" data-id="${r.id}">恢复采集</button>`:r.status==='stale'&&r.platform==='xhs'?`<button class="button" data-action="recover" data-id="${r.id}">检查并恢复</button>`:'<span class="muted">无需操作</span>';
 if(r.stops?.length&&!activeLogin(r))op=`<span class="muted">${r.status==='cooldown'?'等待冷却结束':r.finishedAt?'需检查停止原因':'等待停止收尾'}</span>`;
 if(!activeLogin(r)&&r.platform==='xhs'&&['stale','stopped'].includes(r.status))op+=`<button class="text-button" data-action="open_login" data-id="${r.id}">打开登录窗口</button>`;
 const hints=r.remoteHold?'存在远程停止保护':r.status==='cooldown'?'安全冷却':r.stops?.length?'存在停止保护':r.status==='planned'?'按原安排保持停采':r.remoteChannel==='unavailable'&&r.platform==='xhs'?'远程启动通道上次检查不可用':r.status==='stale'?'先核对进程与保护状态':'';
 const activityAt=r.activity?.foreground?.at||r.activity?.persistence?.at;const heartbeatWarning=['stale','unknown'].includes(r.heartbeatStatus)?'<span class="heartbeat-warning">独立心跳上报中断</span>':'';
 return `<div class="machine-row"><div class="work-cell"><div class="work-name">${esc(r.machine)}</div></div><div class="state-cell"><span class="status"><i class="dot ${color(r)}"></i>${esc(r.statusLabel)}</span><div class="status-info">${activityAt?'活动 '+esc(time(activityAt)):'心跳 '+esc(heartbeat)}${heartbeatWarning}${r.snapshotStale?'<span class="heartbeat-warning">状态副本待更新</span>':''}${resume?'<br>计划恢复 '+esc(short(resume)):''}</div></div><div class="keyword-cell"><span class="topic">${esc(r.topics?.join('、')||'专题待确认')}${r.status==='planned'?' / 上次任务':''}</span><span class="keyword">${esc(r.keyword||(r.awaitingTask?'待领取检索词':'未读到当前检索词'))}</span></div>${articleDates(r)}<div class="row-metrics">${num(r.output?.hour)} <span class="muted">/</span> ${num(r.output?.day)}<small>篇 · 已核验入库</small></div><div class="row-action">${op}${hints?'<div class="recovery-hint">'+esc(hints)+'</div>':''}</div></div>`}).join('')}`}).join('');
 const challenges=platformRows.filter(activeLogin);$('#navCount').textContent=rows.filter(activeLogin).length;$('#challengeCount').textContent=challenges.length+' 项';
 $('#challenges').innerHTML=challenges.length?challenges.map(r=>`<article class="challenge"><div class="challenge-top"><strong>${esc(r.machine)} · ${names[r.platform]}</strong><span class="challenge-type">待处理</span></div><h3>${esc(phase(r.login))}</h3><button class="button" data-login="${r.id}">${r.login.hasQr?'查看二维码':r.login.phase?.includes('sms')?'处理短信验证':'查看处理指引'}</button></article>`).join(''):'<div class="empty">暂无待处理验证</div>';
 const jobs=(state.jobs||[]).filter(j=>visibleWorks.has(j.machine));$('#jobs').innerHTML=jobs.length?[...jobs].reverse().map(j=>`<div class="job"><span>${esc(short(j.createdAt))}</span><strong>${esc(j.machine)} · ${names[j.platform]}</strong><span>${esc(actions[j.action])} / ${esc(jobStates[j.state]||j.state)}</span><span>${esc(j.message)}</span></div>`).join(''):'<div class="empty small">暂无操作记录</div>';
 $('#metricDetails').innerHTML=`<p>文章日期：最近采到显示最后保存的一篇文章的发布日期；入库最早显示新版专题一“文章＋评论”批次当前检索词的文章中，经文章ID、平台和专题核对数据库后最早的发布日期。两个日期均排除旧版只采文章任务和评论的发布日期，也不是采集或入库时间；没有有效日期或未核验到入库时显示“—”。</p><p>帖子增量：当前任务批次的已核验入库事件，按 eventId 去重；今日从北京时间 00:00 起算。无流水时显示“—”，不推断为零。流水缺失会使结果不完整。</p><p>评论近1小时比较：${db.hour?esc(time(db.hour.start))+' 至 '+esc(time(db.hour.end))+'，间隔 '+num(db.hour.minutes)+' 分钟':'没有可用的相近一小时库存基线'}。评论今日比较：${db.day?esc(time(db.day.start))+' 至 '+esc(time(db.day.end)):'没有可用的零点附近库存基线'}。库存净增包含补库，不能直接等同于采集新增。</p><p>当前数据库库存：${Object.values(names).map(n=>`${n} ${num(db.totals?.posts?.[n])}篇 / ${num(db.totals?.comments?.[n])}条评论`).join('；')}。范围为专题一（文章与评论），数据库取样时间 ${esc(time(db.at))}。</p>`;
 document.querySelectorAll('[data-login]').forEach(b=>b.onclick=()=>openLogin(b.dataset.login));
 document.querySelectorAll('[data-action]').forEach(b=>b.onclick=()=>runAction(rows.find(r=>r.id===b.dataset.id),b.dataset.action));
 if(current&&$('#loginDialog').open)updateDialog();countdown();
}
function countdown(){const t=Math.max(0,Math.ceil((state.sampledAt||Date.now()/1000)+300-Date.now()/1000));$('#countdown').textContent=state.refreshing?'正在采样':`下次更新 ${Math.floor(t/60)}:${String(t%60).padStart(2,'0')}`;}
async function runAction(row,action,extra={}){if(!row||busy)return;busy=true;try{const j=await post('/api/action',{machine:row.machine,platform:row.platform,action,sessionId:row.login?.sessionId,idempotencyKey:operationId(),...extra});pendingOperation={id:j.id,sessionId:row.login?.sessionId,action};toast(j.message);$('#dialogMessage').textContent=j.message;await load();refreshSession();}catch(e){toast(e.message);$('#dialogMessage').textContent=e.message;}finally{busy=false}}
function openLogin(id){current=id;$('#smsCode').value='';$('#dialogMessage').textContent='';updateDialog();$('#loginDialog').showModal();refreshSession()}
let loginListBusy=false;
async function refreshLoginList(){
 if(location.hash!=='#verification'||loginListBusy)return;
 loginListBusy=true;
 try{
  const rows=(state.machines||[]).filter(r=>visibleWorks.has(r.machine)&&r.platform===filter);
  await Promise.allSettled(rows.map(async row=>{
   const response=await fetch(`/api/session?machine=${row.machine}&platform=${row.platform}`);
   if(!response.ok)return;const value=await response.json();
   const latest=(state.machines||[]).find(r=>r.id===row.id);
   if(latest&&Number(value.updatedAt||0)>=Number(latest.login?.updatedAt||0))latest.login=value;
  }));
  render();
 }finally{loginListBusy=false;}
}
async function refreshSession(){if(!current||!$('#loginDialog').open)return;const id=current;const row=(state.machines||[]).find(r=>r.id===id);if(!row)return;try{const r=await fetch(`/api/session?machine=${row.machine}&platform=${row.platform}`);if(!r.ok)throw Error();const s=await r.json();if(current===id){if(Number(s.updatedAt||0)>=Number(row.login?.updatedAt||0)){row.login=s;updateDialog()}if(pendingOperation)await load()}}catch{$('#dialogMessage').textContent='无法读取当前登录会话，请稍后重试。'}}
function updateDialog(){const r=(state.machines||[]).find(r=>r.id===current);if(!r)return;const s=r.login||{};const fresh=s.fresh&&Date.now()-Number(s.updatedAt)<45000;$('#dialogTitle').textContent=`${r.machine} · ${names[r.platform]}`;$('#dialogSubtitle').textContent=`${r.worker} / 状态更新 ${time(s.updatedAt)}`;$('#dialogStatus').textContent=fresh?phase(s):'会话已过期，请更新面板状态。';
 const qr=fresh&&s.hasQr;$('#qrBox').hidden=!qr;const u=`/api/qr?machine=${encodeURIComponent(r.machine)}&platform=${r.platform}&sessionId=${encodeURIComponent(s.sessionId)}&generation=${s.imageGeneration}`;if(qr&&$('#qrImage').getAttribute('src')!==u)$('#qrImage').src=u;
 const restart=fresh&&s.restartRequired===true;$('#refreshQr').textContent=restart?'重新开始登录':'刷新二维码';$('#refreshQr').hidden=!fresh||(!restart&&!['waiting_scan','qr_expired','qr_rejected','qr_unavailable'].includes(s.phase));$('#requestSms').hidden=!fresh||restart||!s.phase?.includes('sms');$('#smsForm').hidden=!fresh||restart||!s.sms?.publicKey||s.sms.expiresAt<=Date.now()||!['waiting_sms','sms_rejected'].includes(s.phase);
 const feedback=fresh?dialogFeedback(s):'';$('#loginFeedback').textContent=feedback;$('#loginFeedback').hidden=!feedback;const invalid=fresh&&s.phase==='sms_rejected';$('#smsCode').setAttribute('aria-invalid',String(invalid));
 if(pendingOperation){const job=(state.jobs||[]).find(j=>j.id===pendingOperation.id);const ack=s.ack?.commandId===pendingOperation.id?s.ack:null;if(ack||job&&job.state!=='running'){$('#dialogMessage').textContent=ack?(ack.ok?'操作已执行，等待平台结果。':loginActionError(ack.reason)):(job.message||'操作结果待核验');pendingOperation=null;}}
 const human=fresh&&s.phase?.startsWith('manual_');$('#humanBox').hidden=!human;$('#humanBox').textContent=human?`${phase(s)}。请在 ${r.machine} 的${names[r.platform]}浏览器完成操作，保留窗口。完成后原程序自动核验。`:'';$('#checkLogin').disabled=!fresh;
}
$('#closeDialog').onclick=()=>{$('#loginDialog').close();$('#smsCode').value='';current=null};$('#loginDialog').addEventListener('close',()=>{$('#smsCode').value='';current=null});
$('#qrImage').onerror=()=>{$('#qrBox').hidden=true;$('#dialogMessage').textContent='二维码已过期或无法读取，请更新当前会话。'};
$('#refreshQr').onclick=()=>runAction((state.machines||[]).find(r=>r.id===current),'refresh_qr');$('#requestSms').onclick=()=>runAction((state.machines||[]).find(r=>r.id===current),'request_sms');$('#checkLogin').onclick=()=>runAction((state.machines||[]).find(r=>r.id===current),'login_status');
$('#smsForm').onsubmit=async e=>{e.preventDefault();const r=(state.machines||[]).find(r=>r.id===current);const s=r?.login;let code=$('#smsCode').value;$('#smsCode').value='';if(!/^[0-9]{4,8}$/.test(code)||!s?.sms?.challengeId){toast('请填写当前手机收到的4—8位短信码');return;}try{await runAction(r,'submit_sms',{challengeId:s.sms.challengeId,code});}finally{code='';}};
$('#refresh').onclick=async()=>{try{await post('/api/refresh',{});toast('正在读取新状态，当前采集任务保持运行。');$('#refresh').disabled=true;setTimeout(load,1800)}catch(e){toast(e.message)}};
document.querySelectorAll('[data-filter]').forEach(b=>b.onclick=()=>{filter=b.dataset.filter;keywordPage=1;restrictionPage=1;document.querySelectorAll('[data-filter]').forEach(x=>{x.classList.toggle('active',x===b);x.setAttribute('aria-pressed',String(x===b))});render()});
window.addEventListener('hashchange',applyView);document.querySelectorAll('.sidebar nav a').forEach(a=>a.addEventListener('click',()=>{if(a.hash===location.hash)applyView()}));applyView();load();setInterval(load,15000);setInterval(countdown,1000);setInterval(refreshSession,2000);

const activeKeywordStates=new Set(['collecting','background','resting','cooldown','verification','leased','waiting']);
function restrictionDuration(seconds){
 if(seconds===null||seconds===undefined)return '—';
 const s=Math.max(0,Math.floor(seconds)),d=Math.floor(s/86400),h=Math.floor(s%86400/3600),m=Math.floor(s%3600/60);
 return d?`${d}天${h?` ${h}小时`:''}`:h?`${h}小时${m?` ${m}分`:''}`:m?`${m}分${s%60?` ${s%60}秒`:''}`:`${s}秒`;
}
async function loadRestrictions(){
 if(location.hash!=='#restrictions')return;
 const request=++restrictionRequest;
 const params=new URLSearchParams({platform:filter,days:$('#restrictionDays').value,machine:$('#restrictionMachine').value,page:restrictionPage});
 $('#restrictions').setAttribute('aria-busy','true');
 try{
  const response=await fetch('/api/restrictions?'+params);if(!response.ok)throw Error();const data=await response.json();
  if(request!==restrictionRequest||location.hash!=='#restrictions')return;
  restrictionPage=data.page;restrictionPages=data.pages;
  $('#restrictionSummary').textContent=`${names[filter]} · ${data.days===7?'近一周':'近一天'} · ${data.machine==='all'?'全部机器':data.machine} · ${num(data.total)} 次限制记录`;
  const labels={login:'登录验证',captcha:'人工验证码',security:'安全限制',sms:'短信验证',slider:'滑块验证',click:'点选验证',gateway:'页面访问验证'};
  const states={resolved:'已核验解除',cooling:'冷却中',unconfirmed:'解除待核验'};
  $('#restrictionRows').innerHTML=data.rows.length?data.rows.map(r=>`<li class="restriction-row"><div class="restriction-when" data-label="发生时间"><time>${esc(time(r.started))}</time><small>${r.precision==='observed'?'首次观察时间':r.precision==='recorded'?'日志记录时间':'触发时间'}</small></div><div data-label="机器"><strong>${esc(r.machine)}</strong></div><div data-label="平台限制"><span class="restriction-kind ${esc(r.kind)}">${esc(labels[r.kind]||'平台验证')}</span>${(r.verificationSteps||[]).filter(step=>step.kind!==r.kind).map(step=>`<small>${esc(time(step.observedAt))}<br>首次观察${esc(labels[step.kind]||'人工验证')}</small>`).join('')}</div><div class="restriction-keyword" data-label="检索词">${esc(r.keyword||'—')}</div><div class="restriction-gap" data-label="距上次限制">${r.intervalApproximate&&r.intervalSeconds!==null?'约 ':''}${esc(restrictionDuration(r.intervalSeconds))}</div><div class="restriction-result" data-label="处理状态"><span class="restriction-state ${esc(r.status)}">${esc(states[r.status])}</span>${r.resolved?`<small>${esc(time(r.resolved))}<br>处理用时 ${esc(restrictionDuration(r.resolved-r.started))}</small>`:r.status==='cooling'?`<small>至 ${esc(time(r.cooldown))}</small>`:''}</div></li>`).join(''):'<li class="empty">此范围暂无已记录的平台限制</li>';
  $('#restrictionPageInfo').textContent=`第 ${data.page} / ${data.pages} 页 · 共 ${num(data.total)} 条`;
  $('#restrictionPrev').disabled=data.page<=1;$('#restrictionNext').disabled=data.page>=data.pages;
  const failures=(data.coverage||[]).filter(c=>c.platform===filter&&c.source!=='ok');
  const coverage=data.trackingSince?`持续记录始于 ${time(data.trackingSince)}；此前回填可用日志，历史可能不完整。`:'首次采样后开始持续记录。';
  $('#restrictionCoverage').textContent=coverage+(data.sampledAt?` 每5分钟采样，最近更新 ${time(data.sampledAt)}。`:'')+(failures.length?' 部分来源暂不可读。':'');
 }catch{
  if(request!==restrictionRequest)return;
  $('#restrictionSummary').textContent='限制记录读取失败，请稍后重试';
  $('#restrictionRows').innerHTML='<li class="empty">暂时无法读取限制记录</li>';
  $('#restrictionPageInfo').textContent='';$('#restrictionPrev').disabled=true;$('#restrictionNext').disabled=true;
 }finally{if(request===restrictionRequest)$('#restrictions').setAttribute('aria-busy','false')}
}
for(const id of ['restrictionDays','restrictionMachine'])$('#'+id).onchange=()=>{restrictionPage=1;loadRestrictions()};
$('#restrictionPrev').onclick=()=>{if(restrictionPage>1){restrictionPage--;loadRestrictions()}};
$('#restrictionNext').onclick=()=>{if(restrictionPage<restrictionPages){restrictionPage++;loadRestrictions()}};

function brandProgress(rows){
 const brands=new Map();
 for(const r of rows){
  const name=(r.brand||'未分组').split(/[／/]/)[0].trim()||'未分组';
  if(!brands.has(name))brands.set(name,{brand:name,total:0,pending:0,active:0,retry:0,completed:0,pending_import:0,attention:0});
  const b=brands.get(name);b.total++;
  const bucket=activeKeywordStates.has(r.status)?'active':['pending','retry','completed','pending_import'].includes(r.status)?r.status:'attention';
  b[bucket]++;
 }
 return [...brands.values()];
}
function renderKeywords(){
 const p=state.keywords?.[filter]||{},counts=p.counts||{},all=p.rows||[];
 $('#keywordSource').textContent=p.total?`${names[filter]} · ${num(p.total)} 个词 · 每5分钟更新`:'正在读取任务状态…';
 const done=p.completed||0,total=p.total||0,pct=p.percent||0;
 const active=[...activeKeywordStates].reduce((n,k)=>n+(counts[k]||0),0);
 $('#keywordSummary').innerHTML=`<div class="keyword-progress-heading"><strong>${num(done)} <small>/ ${num(total)} 个词已结案</small></strong><span>${pct}%</span></div><progress max="${total||1}" value="${done}" aria-label="检索词结案进度">${pct}%</progress><div class="keyword-counts"><span>待领取 <b>${num(counts.pending||0)}</b></span><span>执行／等待 <b>${num(active)}</b></span><span>待重试 <b>${num(counts.retry||0)}</b></span><span>已结案待补库 <b>${num(counts.pending_import||0)}</b></span><span>异常／待核实 <b>${num(['failed','expired','unknown','updating'].reduce((n,k)=>n+(counts[k]||0),0))}</b></span></div>${p.source==='unavailable'?'<div class="keyword-source-warning">任务状态读取失败，暂不统计完成进度。</div>':''}`;
 const query=$('#keywordSearch').value.trim().toLocaleLowerCase();
 const rows=brandProgress(all).filter(r=>!query||r.brand.toLocaleLowerCase().includes(query));
 const inventory=state.database?.brands||{},platformName=names[filter];
 const imported=new Map((inventory.source==='ok'?inventory.rows||[]:[]).filter(r=>r.platform===platformName).map(r=>[r.brand,r]));
 const unmatched=(inventory.unassigned||[]).find(r=>r.platform===platformName);
 $('#brandInventoryNote').textContent=inventory.source==='ok'?`入库量为专题一数据库累计库存（含历史数据），按当前记录的检索词归属品牌，品牌内去重。${unmatched&&(unmatched.posts||unmatched.comments)?`未匹配当前词表：${num(unmatched.posts)} 篇文章／${num(unmatched.comments)} 条评论。`:''}`:'品牌入库量暂未核验。';
 const pages=Math.max(1,Math.ceil(rows.length/keywordPageSize));keywordPage=Math.max(1,Math.min(keywordPage,pages));
 $('#keywordMatches').textContent=`${num(rows.length)} 个品牌 · ${num(rows.reduce((n,r)=>n+r.total,0))} 个词`;
 $('#keywordRows').innerHTML=rows.slice((keywordPage-1)*keywordPageSize,keywordPage*keywordPageSize).map(r=>{const done=r.completed+r.pending_import,pct=Math.round(done/r.total*1000)/10,db=imported.get(r.brand);return `<tr><th scope="row" class="brand-name">${esc(r.brand)}</th><td class="brand-total">${num(r.total)}</td>${['pending','active','retry','completed','pending_import','attention'].map(k=>`<td class="${r[k]?'brand-count '+k:'brand-zero'}">${num(r[k])}</td>`).join('')}<td class="brand-progress"><span>${pct}%</span><progress max="${r.total}" value="${done}" aria-label="${esc(r.brand)}结案进度（含待补库）">${pct}%</progress></td><td class="brand-imported">${num(db?.posts)}</td><td class="brand-imported">${num(db?.comments)}</td></tr>`}).join('')||'<tr><td colspan="11" class="empty">没有匹配的品牌</td></tr>';
 $('#keywordPageInfo').textContent=`第 ${keywordPage} / ${pages} 页 · 每页最多 ${keywordPageSize} 个品牌`;
 $('.keyword-pages').hidden=pages<=1;
 $('#keywordPrev').disabled=keywordPage<=1;$('#keywordNext').disabled=keywordPage>=pages;
}
$('#keywordSearch').addEventListener('input',()=>{keywordPage=1;renderKeywords()});
$('#keywordPrev').onclick=()=>{keywordPage--;renderKeywords()};$('#keywordNext').onclick=()=>{keywordPage++;renderKeywords()};

setInterval(refreshLoginList,5000);
