import {configureTiming,timed,timedSync,contentTiming,timingDisposition,timingMarker,timingProgress,timingFailure,timingStop} from './keyword-timing.mjs';
// Browser work pauses in the same process and call stack. No navigation,
// browser closure, queue acceptance or protection reset belongs in this gate.
import fs from 'node:fs/promises';
import path from 'node:path';
import {randomUUID} from 'node:crypto';

export const COLLECTION_PAUSE_VERSION='xhs-inplace-cycle-pause-20261105-v1';
const delay=ms=>new Promise(resolve=>setTimeout(resolve,ms));
const stopped=()=>new Error('STOP_REQUESTED：原位休息期间收到停止请求；保留断点并收尾');

export class CollectionCyclePause {
  constructor(config,{now=Date.now,sleep=delay,random=Math.random,shouldStop=async()=>false,
    onPause,onResume,onState,autoTimer=true}={}){
    for(const k of ['firstDeadlineAtMs','runMinMs','runMaxMs','restMinMs','restMaxMs'])
      if(!Number.isSafeInteger(config[k])||config[k]<=0)throw new Error('INVALID_COLLECTION_PAUSE_CONFIG');
    if(config.runMinMs>config.runMaxMs||config.restMinMs>config.restMaxMs
      ||!config.workerId||!config.cycleId)throw new Error('INVALID_COLLECTION_PAUSE_CONFIG');
    Object.assign(this,{config,now,sleep,random,shouldStop,onPause,onResume,onState,autoTimer});
    this.state={version:COLLECTION_PAUSE_VERSION,workerId:config.workerId,cycleId:config.cycleId,
      supervisorPid:config.supervisorPid,supervisorSessionId:config.supervisorSessionId,
      workerPid:config.workerPid,phase:'collecting',round:1,totalPauseMs:0,deadlineAtMs:config.firstDeadlineAtMs,resumeAtMs:null};
    this.closed=false;this.waiting=null;this.fault=null;this.timer=null;
  }
  async initialize({reuse=false}={}){
    if(reuse)await this.reload();else await this.publish();
    this.arm();return this;
  }
  async reload(){
    if(!this.config.stateFile)return;
    const value=JSON.parse(await fs.readFile(this.config.stateFile,'utf8'));
    if(value.version!==COLLECTION_PAUSE_VERSION||value.workerId!==this.config.workerId
      ||value.cycleId!==this.config.cycleId||!['collecting','resting'].includes(value.phase)
      ||!Number.isSafeInteger(value.deadlineAtMs)||!Number.isSafeInteger(value.round)
      ||value.phase==='resting'&&!Number.isSafeInteger(value.resumeAtMs))throw new Error('COLLECTION_PAUSE_STATE_INVALID');
    this.state=value;
  }
  pick(min,max){return min+Math.floor(this.random()*(max-min+1));}
  activeNow(){return this.now()-Number(this.state.totalPauseMs||0)
    -(this.state.phase==='resting'?Math.max(0,this.now()-this.state.pausedAtMs):0);}
  async publish(){
    this.state.updatedAt=new Date(this.now()).toISOString();
    this.state.resumeAt=this.state.resumeAtMs?new Date(this.state.resumeAtMs).toISOString():null;
    if(this.config.stateFile){
      const file=this.config.stateFile,tmp=file+'.tmp-'+process.pid+'-'+randomUUID();
      await fs.mkdir(path.dirname(file),{recursive:true});
      await fs.writeFile(tmp,JSON.stringify(this.state)+'\n','utf8');
      await fs.rename(tmp,file);
    }
    await this.onState?.({...this.state});
  }
  arm(){
    clearTimeout(this.timer);
    if(!this.autoTimer||this.closed||this.fault)return;
    const ms=this.state.phase==='resting'?0:Math.max(1,this.state.deadlineAtMs-this.now());
    this.timer=setTimeout(()=>{
      // Store failures for the collecting call; never allow a rejected timer
      // promise to disappear or silently permit more browser work.
      this.beforeAction().catch(error=>{this.fault=error;});
    },ms);
    this.timer.unref?.();
  }
  async beforeAction({reload=false}={}){
    if(this.closed)return;
    if(this.fault)throw this.fault;
    if(reload&&!this.waiting)await this.reload();
    if(await this.shouldStop())throw stopped();
    if(this.waiting)return this.waiting;
    if(this.state.phase!=='resting'&&this.now()<this.state.deadlineAtMs)return;
    this.waiting=this.pause();
    try{await this.waiting;}
    catch(error){this.fault=error;throw error;}
    finally{this.waiting=null;}
  }
  async pause(){return timed('round_sleep',()=>this.pauseTimingImpl(),{lane:'hold'});}
  async pauseTimingImpl(){
    clearTimeout(this.timer);
    if(this.state.phase!=='resting'){
      if(await this.shouldStop())throw stopped();
      this.state.phase='resting';timingProgress('rest_started',{reason:'round_deadline',round:this.state.round});
      this.state.pausedAtMs=this.now();
      this.state.resumeAtMs=this.now()+this.pick(this.config.restMinMs,this.config.restMaxMs);
      await this.onPause?.({...this.state});
      await this.publish();
    }
    while(!this.closed&&this.now()<this.state.resumeAtMs){
      if(await this.shouldStop())throw stopped();
      await this.sleep(Math.min(250,this.state.resumeAtMs-this.now()));
    }
    if(this.closed)return;
    if(await this.shouldStop())throw stopped();
    // Revalidate access/lease after the rest and before the blocked action.
    // A login or CAPTCHA protection must win over the elapsed timer.
    await timed('wake_validation',()=>this.onResume?.({...this.state}));
    if(await this.shouldStop())throw stopped();
    this.state.totalPauseMs=Number(this.state.totalPauseMs||0)+Math.max(0,this.now()-this.state.pausedAtMs);
    this.state.phase='collecting';this.state.round++;timingProgress('rest_resumed',{round:this.state.round});
    this.state.resumedAtMs=this.now();this.state.resumeAtMs=null;
    this.state.deadlineAtMs=this.now()+this.pick(this.config.runMinMs,this.config.runMaxMs);
    await this.publish();this.arm();
  }
  async close({terminal=false}={}){
    this.closed=true;clearTimeout(this.timer);
    if(terminal){this.state.phase='stopped';this.state.resumeAtMs=null;await this.publish();}
  }
}

// Playwright constructs locators synchronously. Its actual asynchronous API
// calls pass through the gate, including calls from existing helper modules.
const types=new Set(['Page','Frame','Locator','FrameLocator','ElementHandle','JSHandle',
  'Browser','BrowserContext','Keyboard','Mouse','Touchscreen','CDPSession','Response','Request']);
const sync=new Set(['url','isClosed','context','contexts','pages','mainFrame','frames','frame',
  'viewportSize','browser','browserType','version','isConnected','name','parentFrame','childFrames',
  'locator','frameLocator','first','last','nth','filter','and','or','describe','contentFrame',
  'setDefaultTimeout','setDefaultNavigationTimeout','setMaxListeners','on','once','off','addListener',
  'removeListener','removeAllListeners','prependListener','prependOnceListener','emit','listeners',
  'listenerCount','eventNames','status','statusText','ok','headers','request','response','frame',
  'method','postData','postDataJSON','postDataBuffer','resourceType','isNavigationRequest',
  'redirectedFrom','redirectedTo','failure','timing','fromServiceWorker']);
// Request.response is asynchronous in Playwright; explicitly gate it below.
sync.delete('response');
const objectGates=new WeakMap();
export const collectionWorkNow=object=>objectGates.get(object)?.activeNow()??Date.now();
export function pausePlaywright(object,gate){
  const cache=new WeakMap(),raw=new WeakMap();
  const unwrap=value=>{
    if(raw.has(value))return raw.get(value);
    if(Array.isArray(value))return value.map(unwrap);
    if(value&&Object.getPrototypeOf(value)===Object.prototype)
      return Object.fromEntries(Object.entries(value).map(([k,v])=>[k,unwrap(v)]));
    return value;
  };
  const wrap=value=>{
    if(Array.isArray(value))return value.map(wrap);
    if(!value||typeof value!=='object'||!types.has(String(value.constructor?.name||'').replace(/^_+/,'').replace(/\d+$/,'')))return value;
    if(cache.has(value))return cache.get(value);
    const methods=new Map();
    const proxy=new Proxy(value,{get(target,key){
      if(key==='then')return undefined;
      const member=Reflect.get(target,key,target);
      if(typeof member!=='function'||key==='constructor')return wrap(member);
      if(methods.has(key))return methods.get(key);
      const call=(...args)=>member.apply(target,args.map(unwrap));
      const fn=sync.has(key)||String(key).startsWith('getBy')
        ?(...args)=>wrap(call(...args))
        :async(...args)=>{await gate.beforeAction();return wrap(await call(...args));};
      methods.set(key,fn);return fn;
    }});
    cache.set(value,proxy);raw.set(proxy,value);objectGates.set(value,gate);objectGates.set(proxy,gate);return proxy;
  };
  return wrap(object);
}

export function pauseHeartbeatState(supervisor,pause,now=Date.now()){
  if(supervisor.state!=='collecting'||pause?.version!==COLLECTION_PAUSE_VERSION
    ||pause.phase!=='resting'||pause.supervisorPid!==supervisor.supervisorPid
    ||pause.supervisorSessionId!==supervisor.sessionId||!Number.isSafeInteger(pause.resumeAtMs)
    ||!Number.isSafeInteger(pause.pausedAtMs)||pause.resumeAtMs<=pause.pausedAtMs)return supervisor;
  // Keep reporting resting until the collector actually revalidates and
  // publishes collecting; time alone is not proof of a successful resume.
  return {...supervisor,state:'resting',resumeAt:new Date(pause.resumeAtMs).toISOString(),
    pauseMode:'in_place',pauseRound:pause.round};
}
