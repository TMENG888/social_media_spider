// Never return raw messages, addresses, paths, credentials or stacks.
export const LOGIN_RECOVERY_VERSION='20261020-v6';
const hints={
 ENOENT:'缺少运行文件；按当前阶段补齐对应配置、清单或运行模块。',
 EACCES:'文件或目录无访问权限；检查此节点本地目录权限。',
 EPERM:'操作被系统拒绝；检查文件权限或浏览器资料占用。',
 INVALID_JSON:'配置或监控记录不是有效JSON；检查当前阶段对应文件/记录，不要清空保护。',
 INVALID_CONFIG:'Redis地址、任务池或超时配置无效；核对本平台配置，不要把密码放入URL。',
 INVALID_MANIFEST:'任务清单缺少有效manifestHash；同步本平台原任务清单，不新增或重置任务。',
 REDIS_AUTH_FAILED:'Redis用户名或密码未通过认证；核对本机保存凭据与对应端口账号。',
 REDIS_AUTH_REQUIRED:'Redis要求认证；通过本机隐藏输入配置凭据。',
 REDIS_PERMISSION_DENIED:'Redis账号权限不足；需核对监控键及EVAL/HGET/TIME权限，不要取消认证。',
 REDIS_WRONGTYPE:'Redis监控键类型不符；保留现场核查，不删除或重置键。',
 REDIS_SCRIPT_ERROR:'Redis监控脚本执行失败；保留监控数据，由维护人员核查。',
 ECONNREFUSED:'目标连接被拒绝；核对Redis端口与服务可达性。',
 ETIMEDOUT:'连接超时；检查本机至Redis的网络，不清除保护。',
 REDIS_TIMEOUT:'Redis连接或命令超时；检查网络与服务响应。',
 ENETUNREACH:'网络不可达；检查远端机器网络。',
 EHOSTUNREACH:'目标主机不可达；检查远端机器路由或防火墙。',
 ENOTFOUND:'域名解析失败；核对地址及DNS。',
 EAI_AGAIN:'域名解析暂时失败；网络恢复后再试。',
 ECONNRESET:'连接被重置；检查网络及Redis服务状态。',
 REDIS_CONNECTION_CLOSED:'Redis连接已关闭；网络恢复后重新运行。',
 PAGE_TIMEOUT:'主页访问或页面检查超时；检查浏览器页面和网络。',
 UNKNOWN:'尚未识别的错误；提供本行阶段与错误码，不能据此判定登录失败。',
 WORKER_STILL_RUNNING:'本节点采集进程仍在运行；请先安全停止或等待收尾。',
 WORKER_STATE_UNCONFIRMED:'无法确认本节点锁状态；保留锁和停止标记，先核对采集进程。',
 WORKER_ID_MISMATCH:'任务清单不属于此节点；同步正确节点清单。',
 STATE_PATH_OUTSIDE_WORKER:'状态目录超出此节点；核对stateRoot。',
 CUSTOM_CDP_CONFIGURED:'配置了外部浏览器；不能用默认资料代替其登录。',
 NOT_LOGIN_OR_CAPTCHA:'当前是非登录/验证码事件；保留安全冷却。',
 TIMED_COOLDOWN_PRESERVED:'当前为定时冷却；请由原启动脚本等待。',
 BROWSER_PROFILE_UNAVAILABLE:'浏览器启动失败；核对浏览器文件与资料占用，勿删除锁或强杀进程。',
 LOGIN_NOT_VERIFIED:'页面未能确认登录；检查是否有登录/验证提示，不需要检索关键词。',
 OPERATOR_CANCELLED:'操作已取消；事件保留。',
 LOGIN_STATE_CHANGED:'确认期间登录状态变化；事件未解除。',
 RECOVERY_NOT_APPLIED:'事件已变化或保护不适用；未强行解除，请重新核对。'
};
const stages=new Set(['READ_QUEUE','VALIDATE_WORKER','CHECK_IDLE','OPEN_MONITOR','READ_REDIS_SETTINGS',
 'READ_REDIS_CONFIG','READ_MANIFEST','VALIDATE_MANIFEST','READ_PLATFORM_CONFIG','CONNECT_REDIS',
 'READ_MONITOR_SNAPSHOT','VALIDATE_MONITOR_STATE','PREPARE_PROFILE','LAUNCH_BROWSER',
 'OPEN_HOMEPAGE','VERIFY_LOGIN','CONFIRM_OPERATOR','CLOSE_BROWSER','RECHECK_IDLE','RESOLVE_MONITOR']);
const loginReasons=new Set(['LOGIN_OR_SECURITY_STILL_VISIBLE','PAGE_NOT_READY','APP_REPORTS_LOGGED_OUT',
 'LOGIN_STATE_UNCONFIRMED','BROWSER_CLOSED','PLATFORM_PAGE_REQUIRED','PAGE_CHANGED_DURING_CHECK']);
export function loginCheckSummary(check){
 const result={ok:check?.ok===true,reason:check?.ok===true?'VERIFIED':loginReasons.has(check?.reason)?check.reason:'LOGIN_CHECK_ERROR'};
 if(['rendered_app_login_flag','own_account_navigation'].includes(check?.evidence))result.evidence=check.evidence;
 if(check?.signals)result.signals={
  ready:check.signals.ready===true,blocked:check.signals.blocked===true,
  appLoggedIn:typeof check.signals.appLoggedIn==='boolean'?check.signals.appLoggedIn:null,
  ownAccount:check.signals.ownAccount===true
 };
 return result;
}
export function loginFailure(error,stage){
 const causes=[];const seen=new Set();
 function visit(e){if(!e||typeof e!=='object'||seen.has(e)||causes.length>=12)return;
  seen.add(e);causes.push(e);visit(e.cause);if(Array.isArray(e.errors))for(const item of e.errors)visit(item);}
 visit(error);
 let code;
 for(const e of causes){
  if(Object.hasOwn(hints,e.code)){code=e.code;break;}
  const message=String(e.message||'');
  const explicit=message.match(/^([A-Z_]+)：/);
  if(explicit&&Object.hasOwn(hints,explicit[1])){code=explicit[1];break;}
  if(/^(?:WRONGPASS|ERR invalid (?:username|password)|ERR AUTH)/i.test(message)){code='REDIS_AUTH_FAILED';break;}
  if(/^NOAUTH\b/.test(message)){code='REDIS_AUTH_REQUIRED';break;}
  if(/^NOPERM\b/.test(message)){code='REDIS_PERMISSION_DENIED';break;}
  if(/^WRONGTYPE\b/.test(message)){code='REDIS_WRONGTYPE';break;}
  if(/^ERR (?:Error running script|user_script|.*cjson)/i.test(message)){code='REDIS_SCRIPT_ERROR';break;}
  if(e.name==='SyntaxError'){code='INVALID_JSON';break;}
  if(e.name==='ConnectionTimeoutError'){code='ETIMEDOUT';break;}
  if(e.name==='SocketClosedUnexpectedlyError'){code='REDIS_CONNECTION_CLOSED';break;}
  if(e.name==='TimeoutError'&&/HOMEPAGE|LOGIN/.test(stage)){code='PAGE_TIMEOUT';break;}
 }
 if(!code&&stage==='READ_REDIS_SETTINGS')code='INVALID_CONFIG';
 code||='UNKNOWN';
 return {version:LOGIN_RECOVERY_VERSION,stage:stages.has(stage)?stage:'UNKNOWN_STAGE',code,hint:hints[code]};
}
