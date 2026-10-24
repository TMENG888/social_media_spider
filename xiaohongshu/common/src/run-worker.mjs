import fs from "node:fs/promises";
import {verifyCheckpointCoverage} from './coverage-gate.mjs';
import {supportedCorrectionPolicy} from './correction-lease.mjs';
import {keywordQueueConfirmed as volumeQueueConfirmed,reconcileVolumeCompletion} from './volume-confirmation.mjs';
import path from "node:path";
import { spawn, execFile } from "node:child_process";
import readline from "node:readline/promises";
import { stdin as input, stdout as output } from "node:process";
import mysql from "mysql2/promise";
import { writeJsonAtomic } from "./checkpoint.mjs";
import { POLICY_VERSION, ACCEPTANCE_VERSION, projectForTopic } from "./collection-policy.mjs";
import { RedisDispatcher } from "./redis-dispatcher.mjs";
import { loadTaskManifest } from "./redis-task-manifest.mjs";
import { repairCategoryNull } from "./category-repair.mjs";
import { repairInvalidArticleLinks } from "./link-repair.mjs";
import { summarizeWorkerTasks } from "./worker-status.mjs";
import { collectionFailurePolicy, collectionNodeFailure } from "./collection-failure.mjs";
import { runAuthorPhase } from "./run-author-phase.mjs";
import { verifyTable, mysqlConnectionOptions } from "./import-mysql.mjs";
import { POST_FIELDS, COMMENT_FIELDS } from "./schema.mjs";
import { IMPORT_PENDING_EXIT_CODE, importTaskState } from "./import-recovery.mjs";
import { RateLimitCooldown, restrictionKind, cooldownWorkerExit } from "./rate-limit-cooldown.mjs";
import { cleanupWorkerAsrMedia } from "./cleanup-worker-asr-media.mjs";
import {unchangedRetry} from './retry-no-change.mjs';
import {writeRuntimeStop, recoverOrphanRuntimeStop} from './runtime-stop.mjs';
import {recoverLocalStorageStop,verifyLocalStorage,isStorageFull} from './local-storage-stop.mjs';
import {appendDiagnosticEvent} from './page-diagnostics.mjs';

const root = path.resolve(process.env.XHS_WORKER_ROOT || ".");
const args = Object.fromEntries(process.argv.slice(2).reduce((out, value, index, all) => {
  if (value.startsWith("--")) out.push([value.slice(2), all[index + 1]?.startsWith("--") ? true : all[index + 1]]);
  return out;
}, []));
const mode = String(args.mode || "run");
const phase = String(args.phase || 'auto');
if(!['auto','posts','authors'].includes(phase))throw new Error('phase只允许auto/posts/authors');
const dispatchMode = String(args.dispatch || process.env.XHS_DISPATCH || "local");
if (!["local", "redis"].includes(dispatchMode)) throw new Error("dispatch只允许local或redis");
const onlyTaskId=args['only-task-id']?String(args['only-task-id']):null;
const correctionPolicy=args['correction-policy']?String(args['correction-policy']):null;
if(correctionPolicy&&(!supportedCorrectionPolicy(correctionPolicy)||!onlyTaskId))throw new Error('CORRECTION_REQUIRES_EXACT_TASK_AND_CURRENT_POLICY');
if(onlyTaskId){
  if(dispatchMode!=='redis')throw new Error('SELECTED_TASK_REQUIRES_REDIS');
  const selectedManifest=await loadTaskManifest(path.join(root,'tasks','redis-tasks.json'));
  if(!selectedManifest.tasks.some(t=>(t.redisTaskId||t.id)===onlyTaskId))throw new Error('SELECTED_TASK_NOT_IN_MANIFEST');
}
const skipImport = args["skip-import"] === true || args["skip-import"] === "true" || process.env.XHS_SKIP_IMPORT === "true";
const configuredAcceptance=await fs.readFile(path.join(root,'acceptance-policy.json'),'utf8').then(v=>JSON.parse(v.replace(/^\uFEFF/,'')),e=>{if(e.code==='ENOENT')return null;throw e;});
const volumePolicyEnabled=dispatchMode==='redis'&&!skipImport&&configuredAcceptance?.enabled===true;
if(onlyTaskId&&(skipImport||phase!=='posts'))throw new Error('SELECTED_TASK_REQUIRES_PRODUCTION_POSTS_PHASE');
if(phase==='authors' && (dispatchMode!=='redis'||skipImport))throw new Error('作者阶段只支持Redis生产模式，回填数据表需要MySQL；不会回退到本地分片');
const queueFile = path.resolve(String(args.queue || path.join(root, "tasks", "task-queue.json")));
const maxRuntimeMinutes = Number(args["max-runtime-minutes"] || 0);
const cycleId = args['cycle-id'] ? String(args['cycle-id']) : null;
if (!Number.isFinite(maxRuntimeMinutes) || maxRuntimeMinutes < 0) throw new Error("max-runtime-minutes必须为非负数");
const queue = JSON.parse(await fs.readFile(queueFile, "utf8"));
const workerId = queue.workerId || String(args.worker || "worker-unknown");
const queueDir = path.dirname(queueFile);
const resolveQueuePath = (value, fallback) => path.resolve(queueDir, value || fallback);
const stateRoot = resolveQueuePath(queue.stateRoot, path.join(root, ".state", workerId));
const runsRoot = resolveQueuePath(queue.runsRoot, path.join(root, "runs", workerId));
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const slug = (text) => String(text).normalize("NFKC").replace(/[\\/:*?"<>|\s]+/g, "_").replace(/^_+|_+$/g, "").slice(0, 100);
const now = () => new Intl.DateTimeFormat("sv-SE", { timeZone: "Asia/Shanghai", dateStyle: "short", timeStyle: "medium", hourCycle: "h23" }).format(new Date());
const exists = (value) => fs.access(value).then(() => true).catch(() => false);
const withPythonPath = (siteDir) => [siteDir, process.env.PYTHONPATH].filter(Boolean).join(path.delimiter);
const execFilePromise = (file, childArgs, options = {}) => new Promise((resolve, reject) =>
  execFile(file, childArgs, options, (error, stdout, stderr) => error ? reject(Object.assign(error, { stdout, stderr })) : resolve({ stdout, stderr })));
const runVisible = (file, childArgs, { cwd, env, timeoutMs }) => new Promise((resolve, reject) => {
  let settled = false;
  const child = spawn(file, childArgs, { cwd, env, stdio: "inherit", windowsHide: false });
  const finish = (error) => {
    if (settled) return;
    settled = true;
    clearTimeout(timer);
    error ? reject(error) : resolve();
  };
  const timer = setTimeout(() => {
    child.kill();
    finish(new Error(`ASR dependency installation timed out after ${Math.round(timeoutMs / 60000)} minutes`));
  }, timeoutMs);
  child.once("error", finish);
  child.once("exit", (code, signal) => finish(code === 0 ? null : new Error(`ASR dependency installation failed (code=${code ?? "null"}, signal=${signal ?? "none"})`)));
});
const tasks = (queue.tasks || []).filter((task) => task.enabled !== false).map(task => ({ ...task,
  projectName: projectForTopic(task.topic, task.projectName),
  collectComments: task.topic === "专题一" ? false : task.topic === "专题二" ? true : task.collectComments !== false
}));

await fs.mkdir(runsRoot, { recursive: true });
await fs.mkdir(stateRoot, { recursive: true });

async function environmentCheck() {
  let globalManifest = null, manifestError = null;
  if (dispatchMode === "redis") {
    try { globalManifest = await loadTaskManifest(path.join(root, "tasks", "redis-tasks.json")); }
    catch (error) { manifestError = String(error.message || error); }
  }
  const browserExecutable = process.env.XHS_BROWSER_EXECUTABLE || path.join(root, "runtime", "browsers", "chrome-win64", "chrome.exe");
  let config = {};
  try { config = JSON.parse(await fs.readFile(path.join(root, "config.json"), "utf8")); } catch {}
  if(phase==='authors')config.asrEnabled=false;
  const portablePython = path.join(root, "runtime", "python", "python.exe");
  const configuredPython = process.env.XHS_ASR_PYTHON || (await exists(portablePython) ? portablePython : config.asrPythonExecutable || "python");
  const asrPython = configuredPython !== "python" && !path.isAbsolute(configuredPython) ? path.resolve(root, configuredPython) : configuredPython;
  const configuredSite = process.env.XHS_ASR_SITE || path.join(root, "runtime", "python-site");
  const asrPythonSite = path.isAbsolute(configuredSite) ? configuredSite : path.resolve(root, configuredSite);
  const configuredModel = process.env.XHS_ASR_MODEL_PATH || config.asrModelPath || path.join(root, "runtime", "asr-models", "faster-whisper-small");
  const asrModelPath = path.isAbsolute(configuredModel) ? configuredModel : path.resolve(root, configuredModel);
  const asrRequirements = path.join(root, "requirements-asr.txt");
  const asrThreads = String(Math.max(1, Number(process.env.XHS_ASR_CPU_THREADS || config.asrCpuThreads || 1)));
  const asrEnv = { ...process.env, PYTHONUTF8: "1", PYTHONPATH: withPythonPath(asrPythonSite),
    OMP_NUM_THREADS: asrThreads, MKL_NUM_THREADS: asrThreads,
    OPENBLAS_NUM_THREADS: asrThreads, NUMEXPR_NUM_THREADS: asrThreads };
  const probeAsr = () => execFilePromise(asrPython,
    ["-B", "-c", "import faster_whisper, av, numpy; print('ASR dependencies ready')"],
    { timeout: 30000, windowsHide: true, env: asrEnv, maxBuffer: 4 * 1024 * 1024 });
  // Do not instantiate Whisper during environment preflight. Loading the full
  // model here doubles startup memory and can reject an otherwise healthy
  // collector before any Redis task is claimed. Runtime initialization belongs
  // to the durable background ASR queue, where failures remain retryable.
  const probeAsrModelAssets = async () => {
    const required = ["config.json", "model.bin", "tokenizer.json", "vocabulary.txt"];
    const missing = [];
    for (const name of required) {
      const target = path.join(asrModelPath, name);
      try {
        const stat = await fs.stat(target);
        if (!stat.isFile() || stat.size <= 0) missing.push(name);
      } catch { missing.push(name); }
    }
    if (missing.length) throw new Error(`离线ASR模型文件缺失或为空：${missing.join(", ")}`);
  };
  const checks = {
    workerId, checkedAt: now(), nodeVersion: process.version, queueFile,
    dispatchMode, queueExists: await exists(queueFile), taskCount: dispatchMode === "redis" ? globalManifest?.taskCount || 0 : tasks.length,
    localShardTaskCount: tasks.length, manifestError,
    browserExecutable, browserExists: await exists(browserExecutable),
    indexExists: await exists(path.join(root, "src", "index.mjs")),
    checkpointModuleExists: await exists(path.join(root, "src", "checkpoint.mjs")),
    importerExists: await exists(path.join(root, "src", "import-mysql.mjs")),
    asrPython, asrPythonConfigured: Boolean(asrPython), asrPythonSite, asrModelPath,
    asrPythonExists: path.isAbsolute(asrPython) ? await exists(asrPython) : true,
    asrEnabled: config.asrEnabled !== false, asrDependenciesReady: config.asrEnabled === false,
    asrModelReady: config.asrEnabled === false,
    asrAutoInstall: !volumePolicyEnabled&&config.asrAutoInstall !== false, asrBootstrapAttempted: false,
    writable: true
  };
  if (checks.asrEnabled && checks.asrPythonExists) {
    try {
      await probeAsr();
      checks.asrDependenciesReady = true;
    } catch (initialError) {
      checks.asrDependencyError = String(initialError.stderr || initialError.message || initialError).split("\n").slice(-3).join(" ");
      if (initialError.code === "ENOENT") checks.asrPythonExists = false;
      if (checks.asrPythonExists && checks.asrAutoInstall && await exists(asrRequirements)) {
        checks.asrBootstrapAttempted = true;
        console.log(`[ASR environment] Dependencies are missing. Installing them into ${asrPythonSite}`);
        try {
          await fs.mkdir(asrPythonSite, { recursive: true });
          await runVisible(asrPython, ["-m", "pip", "install", "--disable-pip-version-check", "--no-input", "--prefer-binary", "--upgrade", "--target", asrPythonSite, "-r", asrRequirements],
            { cwd: root, env: asrEnv, timeoutMs: Number(config.asrInstallTimeoutMs || 1800000) });
          await probeAsr();
          checks.asrDependenciesReady = true;
          checks.asrBootstrapSucceeded = true;
          delete checks.asrDependencyError;
          console.log("[ASR environment] Dependency installation completed.");
        } catch (bootstrapError) {
          checks.asrBootstrapSucceeded = false;
          checks.asrBootstrapError = String(bootstrapError.stderr || bootstrapError.message || bootstrapError).split("\n").slice(-5).join(" ");
        }
      }
    }
    if (checks.asrDependenciesReady) {
      try {
        await probeAsrModelAssets();
        checks.asrModelReady = true;
        checks.asrRuntimeProbeDeferred = true;
      } catch (modelError) {
        checks.asrModelError = String(modelError.stderr || modelError.message || modelError).split("\n").slice(-5).join(" ");
      }
    }
  }
  try {
    const probe = path.join(stateRoot, `.write-probe-${process.pid}`);
    await fs.writeFile(probe, "ok", "utf8");
    await fs.unlink(probe);
  } catch { checks.writable = false; }
  checks.asrRequiredForAcceptance=!volumePolicyEnabled;
  checks.ok = !manifestError && checks.queueExists && checks.taskCount > 0 && checks.browserExists && checks.indexExists && checks.checkpointModuleExists && checks.importerExists && (volumePolicyEnabled || checks.asrPythonExists && checks.asrDependenciesReady && checks.asrModelReady) && checks.writable;
  await writeJsonAtomic(path.join(stateRoot, "environment_check.json"), checks);
  return checks;
}

const checks = await environmentCheck();
if (mode === "check") {
  console.log(JSON.stringify(checks, null, 2));
  process.exit(checks.ok ? 0 : 1);
}
if (!checks.ok) throw new Error(`环境检查失败，请查看 ${path.join(stateRoot, "environment_check.json")}`);
console.log("[环境预检] 通过");

const lockFile = path.join(stateRoot, "worker.lock");
let lockHandle = null;
async function acquireLock() {
  try {
    lockHandle = await fs.open(lockFile, "wx");
  } catch (error) {
    if (error.code !== "EEXIST") throw error;
    let pid = null;
    try { pid = Number(JSON.parse(await fs.readFile(lockFile, "utf8")).pid); } catch {}
    let alive = false;
    if (pid) try { process.kill(pid, 0); alive = true; } catch {}
    if (alive) throw new Error(`${workerId} 已在运行（PID ${pid}），禁止重复启动`);
    await fs.unlink(lockFile).catch(() => {});
    lockHandle = await fs.open(lockFile, "wx");
  }
  await lockHandle.writeFile(JSON.stringify({ workerId, pid: process.pid, startedAt: now() }));
}
await acquireLock();

const stopFile = path.join(stateRoot, "stop.requested");
const {RemoteStopControl}=await import('./remote-stop-control.mjs');
const supervisorStopFile = process.env.XHS_SUPERVISOR_STOP_FILE ? path.resolve(process.env.XHS_SUPERVISOR_STOP_FILE) : null;
// A launch is not authorization to erase a human, remote, or safety hold.
// Only verified timer or recovered local-disk markers may be archived under
// the worker lock. Human/remote/unknown stops remain authoritative.
let stopSignalCount = 0;
const requestStop = async (signal) => {
  stopSignalCount += 1;
  if (stopSignalCount > 1) process.exit(130);
  await fs.writeFile(stopFile, `${signal} ${now()}\n`, "utf8").catch(() => {});
  console.warn(`[安全停止] 收到${signal}，已通知采集器完成当前笔记后收尾；再次按Ctrl+C将强制退出`);
};
process.on("SIGINT", () => void requestStop("SIGINT"));
if (process.platform === "win32") process.on("SIGBREAK", () => void requestStop("SIGBREAK"));

async function promptCredentials() {
  if (process.env.MYSQL_USER && process.env.MYSQL_PASSWORD) return;
  const rl = readline.createInterface({ input, output });
  const user = (await rl.question("MySQL用户名: ")).trim();
  rl.close();
  const password = await new Promise((resolve, reject) => {
    execFile("powershell", ["-NoProfile", "-Command", "$p=Read-Host 'MySQL密码' -AsSecureString; $b=[Runtime.InteropServices.Marshal]::SecureStringToBSTR($p); try {[Runtime.InteropServices.Marshal]::PtrToStringBSTR($b)} finally {[Runtime.InteropServices.Marshal]::ZeroFreeBSTR($b)}"], (error, stdout) => error ? reject(error) : resolve(stdout.trim()));
  });
  if (!user || !password) throw new Error("MySQL用户名或密码为空");
  process.env.MYSQL_USER = user;
  process.env.MYSQL_PASSWORD = password;
}

async function verifyDatabaseConnection() {
  const connectionOptions = mysqlConnectionOptions();
  const { host, port, database } = connectionOptions;
  const statusPath = path.join(stateRoot, "mysql_connection_check.json");
  const status = { checkedAt: now(), host, port, database, user: process.env.MYSQL_USER, connected: false, tables: {}, writePermission: false };
  console.log(`[数据库预检] 正在连接 ${host}:${port}/${database}`);
  let connection;
  try {
    connection = await mysql.createConnection(connectionOptions);
    await connection.query("SELECT 1");
    for (const table of ["ods_social_media_post", "ods_social_media_comment"]) {
      const fields = table === "ods_social_media_post" ? POST_FIELDS : COMMENT_FIELDS;
      const schema = await verifyTable(connection, table, fields);
      status.tables[table] = { accessible: true, columnCount: schema.columnCount,
        requiredFields: schema.requiredFields, extraFields: schema.extraFields, orderMatches: schema.orderMatches };
      const names = fields.map((field) => `\`${field}\``).join(",");
      await connection.query(`INSERT INTO \`${table}\` (${names}) SELECT ${names} FROM \`${table}\` WHERE 1=0`);
      await connection.query(`UPDATE \`${table}\` SET \`id\`=\`id\` WHERE 1=0`);
    }
    status.connected = true;
    status.writePermission = true;
    status.ok = true;
    await writeJsonAtomic(statusPath, status);
    console.log("[数据库预检] 连接、表结构及INSERT/UPDATE权限均通过");
  } catch (error) {
    status.ok = false;
    status.error = String(error.message || error);
    await writeJsonAtomic(statusPath, status);
    throw new Error(`数据库预检失败，爬虫尚未启动：${status.error}；详情见 ${statusPath}`);
  } finally {
    await connection?.end().catch(() => {});
  }
}

const runChild = (childArgs, env = {}) => new Promise((resolve) => {
  const child = spawn(process.execPath, childArgs, { cwd: root, stdio: "inherit", env: { ...process.env, ...env } });
  child.on("error", (error) => resolve({ code: 1, error: String(error.message || error) }));
  child.on("exit", (code, signal) => resolve({ code: code ?? 1, signal }));
});

let browserProcess = null;
let dispatcher = null;
let runtimeTimer = null;
let runtimeStopRequest = null;
let fatalError = null;
let remoteControl=null;
let cooldown=null, stopCooldownMonitor=null, cooldownMonitorError=null;
const statusFile = path.join(runsRoot, "worker_status.json");
let status = { workerId, mode, dispatchMode, cycleId, startedAt: now(), finishedAt: null, tasks: [] };
let diagnosticPhase='starting',lifecycleQueue=Promise.resolve(),diagnosticKeyword='';
const lifecycleFile=path.join(runsRoot,'collection-lifecycle-'+now().slice(0,10)+'.jsonl');
function markLifecycle(stage,details={}) {
  const previousPhase=diagnosticPhase;diagnosticPhase=stage;
  const event={at:new Date().toISOString(),workerId,cycleId,keyword:diagnosticKeyword,stage,previousPhase,...details};
  lifecycleQueue=lifecycleQueue.then(()=>appendDiagnosticEvent(lifecycleFile,event));
  return lifecycleQueue;
}
await markLifecycle('worker_started');
try {
  status.storageStopRecovery=await recoverLocalStorageStop({stopFile,supervisorStopFile,
    workerId,lockFile,storagePaths:[stateRoot,runsRoot]});
  if(status.storageStopRecovery.reason!=='not_local_storage_marker'){
    console.log('[本机存储恢复] '+JSON.stringify(status.storageStopRecovery));
    await markLifecycle('startup_storage_recovery',status.storageStopRecovery);
  }
  if(!status.storageStopRecovery.ready)
    throw Object.assign(new Error('STOP_REQUESTED：本节点停止保护保留，原因='+status.storageStopRecovery.reason),{code:'STOP_REQUESTED'});
  status.startupStopRecovery = await recoverOrphanRuntimeStop({stopFile,
    supervisorStopFile, workerId, cycleId});
  if (status.startupStopRecovery.reason !== 'no_stop_marker') {
    console.log('[停止标记核查] ' + JSON.stringify(status.startupStopRecovery));
    await markLifecycle('startup_stop_recovery', status.startupStopRecovery);
  }
  if (!status.startupStopRecovery.ready)
    throw Object.assign(new Error('STOP_REQUESTED：停止标记保留，原因=' + status.startupStopRecovery.reason
      + '；未领取任务或访问平台'), {code:'STOP_REQUESTED'});
  if(await exists(stopFile) || supervisorStopFile && await exists(supervisorStopFile))
    throw Object.assign(new Error('STOP_REQUESTED：已有停止标记，未领取任务或访问平台'),{code:'STOP_REQUESTED'});
  status.storagePreflight=await verifyLocalStorage([stateRoot,runsRoot]);
  if(!status.storagePreflight.ready)
    throw Object.assign(new Error('本机磁盘预检失败：'+status.storagePreflight.reason+'；请释放至少2GiB空间并确认目录可写，未领取任务'),{code:'LOCAL_STORAGE_UNAVAILABLE'});
  if(dispatchMode==='redis' && !skipImport){
    remoteControl=await RemoteStopControl.open(root,path.dirname(stateRoot));
    await remoteControl.gate();remoteControl.watch();
  }
  try {
    const cleanupConfig = JSON.parse((await fs.readFile(path.join(root, "config.json"), "utf8")).replace(/^\uFEFF/, ""));
    await cleanupWorkerAsrMedia({ stateRoot, mediaName: "asr-media", keepMedia: cleanupConfig.asrKeepMedia === true, dryRun: false });
  } catch (error) { console.warn(`[ASR媒体清理] 跳过本轮清理，不影响采集：${error.message}`); }
  if(dispatchMode==='redis' && !skipImport){
    cooldown=await RateLimitCooldown.open({root,stateRoot,workerId});
    // Direct Node invocations also honor persisted cooldown before browser/SQL.
    await cooldown.assertReady();
    stopCooldownMonitor=cooldown.monitor(stopFile,{onStop:error=>{
      cooldownMonitorError=error;
      console.warn(isStorageFull(error)?
        '[本机存储保护] ENOSPC：本节点磁盘空间不足或无法写入状态文件；仅本节点收尾停止，不发布共享冷却':
        '[平台保护] '+(error.code||'COOLDOWN_STATE_UNAVAILABLE')+'：本节点需人工处理、共享冷却生效或状态不可确认；当前数据收尾后停止');
    }});
  }
  if (dispatchMode === "redis") {
    dispatcher = await RedisDispatcher.open({ root, stateRoot, workerId, skipImport, stopFile, selectedTaskId:onlyTaskId });
    status.campaign = dispatcher.campaign;
    if(cooldown){
      dispatcher.cooldown=cooldown;
      cooldown.bindQueue(dispatcher.queue);
    }
  }
  if (!skipImport) {
    await promptCredentials();
    await verifyDatabaseConnection();
    if(!onlyTaskId){
    const categoryRepair = await repairCategoryNull({ runsRoot, stateRoot });
    console.log(`[分类修复] 本地${categoryRepair.localRowsNormalized}条，数据库文章${categoryRepair.postsUpdated}条、评论${categoryRepair.commentsUpdated}条已统一为NULL${categoryRepair.localFileErrors.length ? `；${categoryRepair.localFileErrors.length}个占用中的本地文件稍后重试` : ""}`);
    const linkRepair = await repairInvalidArticleLinks({ stateRoot });
    console.log(`[链接修复] 数据库文章${linkRepair.postsUpdated}条、评论${linkRepair.commentsUpdated}条已恢复为对应文章详情链接`);
    }
  }
  const workerNumber = Number(String(workerId).match(/(\d+)$/)?.[1] || 1);
  const cdpPort = Number(process.env.XHS_CDP_PORT || (9221 + workerNumber));
  const browserExecutable = process.env.XHS_BROWSER_EXECUTABLE || path.join(root, "runtime", "browsers", "chrome-win64", "chrome.exe");
  await cooldown?.assertReady();
  if(await exists(stopFile))throw new Error('STOP_REQUESTED：启动期间收到安全停止请求');
  if (!process.env.XHS_CDP_URL) {
    browserProcess = spawn(browserExecutable, [`--remote-debugging-port=${cdpPort}`, "--remote-allow-origins=*", "--no-first-run", "--no-default-browser-check", `--user-data-dir=${path.join(stateRoot, "browser-profile")}`], { stdio: "ignore", windowsHide: false });
    await sleep(2500);
  }
  const asrThreads = String(Math.max(1, Number((await fs.readFile(path.join(root, "config.json"), "utf8").then(JSON.parse).catch(() => ({}))).asrCpuThreads || 1)));
  const childEnv = { XHS_COOLDOWN_CAMPAIGN:cooldown?.campaign || '', XHS_COOLDOWN_WORKER_ID:workerId, XHS_DISPATCH: dispatchMode, XHS_ASR_PYTHON: checks.asrPython, XHS_ASR_MODEL_PATH: checks.asrModelPath, PYTHONUTF8: "1", PYTHONPATH: withPythonPath(checks.asrPythonSite), XHS_SKIP_IMPORT: String(skipImport), PLAYWRIGHT_BROWSERS_PATH: process.env.PLAYWRIGHT_BROWSERS_PATH || path.join(root, "runtime", "browsers"), XHS_CDP_URL: process.env.XHS_CDP_URL || `http://127.0.0.1:${cdpPort}`, XHS_BROWSER_EXECUTABLE: browserExecutable,
    OMP_NUM_THREADS: asrThreads, MKL_NUM_THREADS: asrThreads,
    OPENBLAS_NUM_THREADS: asrThreads, NUMEXPR_NUM_THREADS: asrThreads };
  try {
    const old = JSON.parse(await fs.readFile(statusFile, "utf8"));
    status.previousRun = { startedAt: old.startedAt, finishedAt: old.finishedAt };
  } catch {}
  await writeJsonAtomic(statusFile, status);

  if (maxRuntimeMinutes > 0) {
    const deadline = Date.now() + Math.round(maxRuntimeMinutes * 60000);
    status.runtimeLimitMinutes = maxRuntimeMinutes;
    status.deadline = new Date(deadline).toISOString();
    console.log(`[限时采集] 已启动${maxRuntimeMinutes}分钟计时；到时安全停止，不强制打断当前笔记或ASR`);
    runtimeTimer = setTimeout(() => {
      markLifecycle('runtime_limit_reached',{minutes:maxRuntimeMinutes,phaseAtDeadline:diagnosticPhase});
      console.warn(`[限时采集] 已到${maxRuntimeMinutes}分钟，发出安全停止请求`);
      runtimeStopRequest = writeRuntimeStop({stopFile, supervisorStopFile, cycleId, workerId,
        minutes: maxRuntimeMinutes}).then(marker => {
          if (marker) status.runtimeStop = marker;
        }).catch(error => {
          fatalError ||= error;
          console.warn('[Cycle stop] Runtime stop marker could not be saved; automatic resume disabled.');
        });
    }, Math.max(1, deadline - Date.now()));
  }

  for await (const [taskIndex, task] of (phase==='authors' ? [] : dispatcher ? dispatcher.tasks({taskId:onlyTaskId,...(correctionPolicy?{correctionPolicy}:{})}) : tasks.entries())) {
    if (await exists(stopFile)) break;
    console.log(`[工作节点进度] ${workerId}：本机第${taskIndex + 1}词${dispatcher ? `（全局任务池${dispatcher.manifest.taskCount}词）` : `/${tasks.length}`}，开始关键词“${task.keyword}”，专题=${task.topic || ""}，评论=${task.collectComments !== false ? "采集" : "不采集"}`);
    const baseSubdir = dispatcher ? path.join("redis", dispatcher.campaign, task.topic || "default", `${slug(task.keyword)}-${task.redisTaskId.slice(-12)}`) : path.join(task.topic || "default", slug(task.keyword));
    const taskSubdir=dispatcher?.current?.recollectionPolicy?path.join(baseSubdir,dispatcher.current.recollectionPolicy):baseSubdir;
    const taskDir = path.join(runsRoot, taskSubdir);
    const stateDir = path.join(stateRoot, taskSubdir);
    const taskEnv = { ...childEnv, ...dispatcher?.env(),XHS_MEDIA_CORRECTION_ARCHIVE:path.join(stateDir,'media-corrections','mysql-subtitles.jsonl') };
    const checkpointDb = path.join(stateDir, "checkpoint.sqlite");
    const taskStatusPath = path.join(taskDir, "task_status.json");
    await fs.mkdir(taskDir, { recursive: true });
    await fs.mkdir(stateDir, { recursive: true });
    let previous = null;
    try { previous = JSON.parse(await fs.readFile(taskStatusPath, "utf8")); } catch {}
    let importedAlready = false;
    try { importedAlready = JSON.parse(await fs.readFile(path.join(taskDir, "mysql_import_status.json"), "utf8")).status === "success"; } catch {}
    if (!dispatcher && mode === "run" && previous?.policyVersion === POLICY_VERSION && previous?.coverage?.policy==='20261015-scoped-usable-db-80-v3' && previous.coverage.ok===true && previous?.scopeAcceptance?.acceptanceVersion===ACCEPTANCE_VERSION && previous?.searchAcceptance?.ok===true && previous?.status === "completed" && !skipImport && importedAlready) {
      console.log(`[工作节点进度] ${workerId}：${taskIndex + 1}/${tasks.length}，已完成，跳过“${task.keyword}”`);
      status.tasks.push({ ...previous, skipped: true });
      continue;
    }
    if (!dispatcher && mode === "retry" && previous && !["failed", "incomplete", "interrupted", "partial_stopped", "partial_error", "login_required", "risk_controlled", "import_failed", "import_pending", "running"].includes(previous.status)) continue;
    const startedAt = now();
    const runId = `${Date.now()}-${process.pid}-${taskIndex}`;
    const cutoff = task.cutoff || queue.cutoff || task.minPublishedDate || queue.minPublishedDate || "2026-01-01";
    await writeJsonAtomic(taskStatusPath, { workerId, taskId: task.id || null, keyword: task.keyword, status: "running", runId, policyVersion: POLICY_VERSION, startedAt, checkpointDb });

    if (previous && await exists(checkpointDb)) {
      console.log(`[中断恢复] ${task.keyword}：先从断点库恢复已完成数据`);
      const recovery = await runChild([path.join(root, "src", "checkpoint-tool.mjs"), "--db", checkpointDb, "--output-dir", taskDir, "--keyword", task.keyword, "--project-name", task.projectName, "--cutoff", cutoff, "--collect-comments", String(task.collectComments)]);
      if (recovery.code !== 0) throw new Error(`${task.keyword}断点导出失败，退出码${recovery.code}`);
      if (!skipImport && await exists(path.join(taskDir, "ods_social_media_post.jsonl"))) {
        await dispatcher?.verify();
        const recoveredImport = await runChild([path.join(root, "src", "import-mysql.mjs"), "--input-dir", taskDir, "--commit", "--auto-approved"], taskEnv);
        if (recoveredImport.code === IMPORT_PENDING_EXIT_CODE) {
          const pendingRecord = { workerId, runId, policyVersion: POLICY_VERSION, taskId: task.id || null,
            topic: task.topic || null, keyword: task.keyword, projectName: task.projectName || null,
            collectComments: task.collectComments !== false, startedAt, finishedAt: now(),
            status: 'import_pending', importExitCode: recoveredImport.code, outputDir: taskDir, stateDir, checkpointDb,
            posts: previous.posts ?? null, commentThreads: previous.commentThreads ?? null,
            error: '入库仍繁忙；本轮仅恢复本地数据，未访问平台，等待下轮补库' };
          if (dispatcher) {
            const disposition=await exists(stopFile)?'release':'defer';
            const confirmation = await dispatcher.finish(disposition, pendingRecord);
            pendingRecord.redisReleased = disposition==='release';
            pendingRecord.redisFailedHandled = disposition==='defer';
            pendingRecord.redisDisposition = String(confirmation?.status || 'pending');
          }
          await writeJsonAtomic(taskStatusPath, pendingRecord);
          status.tasks.push(pendingRecord);
          await writeJsonAtomic(statusFile, { ...status, finishedAt: null });
          console.warn(`[入库待补] ${task.keyword}：本地断点保留，任务已归还；本轮不继续采集，休息后再试。`);
          break;
        }
        if (recoveredImport.code !== 0) throw new Error(`${task.keyword}断点恢复入库失败，退出码${recoveredImport.code}`);
      }
      console.log(`[中断恢复] ${task.keyword}：已恢复，继续未完成笔记`);
    }

    const configArgs = [];
    if (task.collectorConfig) {
      const taskConfig = path.join(taskDir, "collector-config.json");
      await writeJsonAtomic(taskConfig, task.collectorConfig);
      configArgs.push("--config", taskConfig);
    }
    await cooldown?.assertReady();
    diagnosticKeyword=task.keyword;
    await markLifecycle('collector_started',{runId});
    const result = await runChild([
      path.join(root, "src", "index.mjs"), "--query", task.keyword,
      ...configArgs,
      "--run-id", runId, "--skip-import", String(skipImport),
      "--project-name", task.projectName || "",
      "--cutoff", cutoff,
      "--max-notes", String(task.maxNotes || queue.maxNotes || 3),
      "--max-search-scrolls", String(task.maxSearchScrolls ?? queue.maxSearchScrolls ?? 0),
      "--search-stop-window", String(task.searchStopWindow || queue.searchStopWindow || 8),
      "--import-batch-size", String(task.importBatchSize || queue.importBatchSize || 20),
      "--collect-all-current-year", String(task.collectAllCurrentYear ?? queue.collectAllCurrentYear ?? true),
      "--collect-comments", String(task.collectComments !== false),
      "--browser-executable", browserExecutable, "--output-dir", taskDir,
      "--profile-dir", path.join(stateRoot, "browser-profile"),
      "--checkpoint-db", checkpointDb, "--stop-file", stopFile
    ], taskEnv);

    let collector = { status: result.signal ? "interrupted" : "partial_error", error: "COLLECTOR_STATUS_MISSING_OR_STALE：采集器未提交本轮有效状态报告" };
    try {
      const reported = JSON.parse(await fs.readFile(path.join(taskDir, "collector_status.json"), "utf8"));
      if (reported.runId === runId) collector = reported;
    } catch {}
    if (result.code !== 0 && collector.status === "completed") collector.status = "partial_error";
    await markLifecycle('collector_finished',{runId,collectorStatus:collector.status,collectorExitCode:result.code,
      firstFailureAt:collector.firstFailureAt||null,error:collector.error||null,pageDiagnostics:collector.pageDiagnostics||null});
    // Same event ID as collector: fallback publication cannot count a second incident.
    if(cooldown && restrictionKind(collector.error)){
      try{await cooldown.record(collector.error,'post:'+runId);}
      catch(error){
        // Keep preserving/importing the collected data, but fail closed on restart.
        fatalError ||= error;
        await fs.writeFile(stopFile,'COOLDOWN_STATE_UNAVAILABLE',{encoding:'utf8',flag:'wx'}).catch(e=>{if(e.code!=='EEXIST')throw e;});
      }
    }
    let importResult = null;
    if (!skipImport && !dispatcher?.lost && await exists(path.join(taskDir, "ods_social_media_post.jsonl"))) {
      await dispatcher?.verify();
      console.log(`[数据保全入库] ${workerId}：${task.keyword}，采集状态=${collector.status}`);
      await markLifecycle('preservation_import_started',{runId,collectorStatus:collector.status});
      importResult = await runChild([path.join(root, "src", "import-mysql.mjs"), "--input-dir", taskDir, "--commit", "--auto-approved"], taskEnv);
      await markLifecycle('preservation_import_finished',{runId,importExitCode:importResult.code});
      console.log(`[数据保全入库] ${workerId}：${task.keyword}，${importResult.code === 0 ? "成功" : `失败（退出码${importResult.code}）`}`);
    }
    const collectorFailure = collectionNodeFailure(collector);
    const collectionStatus = collector.status;
    const collectionError = collector.error || null;
    let taskState = collector.status || (result.code === 0 ? "completed" : "partial_error");
    if (collectorFailure.stopNode) taskState = collectorFailure.status;
    if (!skipImport) taskState = importTaskState(taskState, importResult?.code, collectorFailure);
    if (dispatcher?.lost) taskState = "lease_lost";
    const stopping = stopSignalCount > 0 || await exists(stopFile);
    const observation=collector.retryObservation;
    const noChange=observation && unchangedRetry(observation.before,observation.after,{...observation,
      status:taskState,error:collector.error||'',stopped:stopping,importOk:!skipImport&&importResult?.code===0,
      runtimeUnavailable:collector.asrJobs?.runtimeUnavailable||observation.asrDrainConfirmed===false,
      pendingAsr:collector.asrJobs?.pendingTotal||0});
    let coverage={ok:false,reason:'DB_READBACK_NOT_PERFORMED'};
    if(dispatcher?.volume&&!dispatcher.lost&&!stopping){
      try{coverage=await dispatcher.volume.read(task.redisTaskId||task.id);if(coverage.ok&&!collectorFailure.stopNode)taskState='completed';}
      catch(error){coverage={ok:false,reason:'DB_READBACK_FAILED',errorCode:error.code||'READBACK_ERROR'};}
    }else if(!skipImport&&importResult?.code===0&&!dispatcher?.lost&&!stopping){
      try{coverage=await verifyCheckpointCoverage({checkpointDb,keyword:task.keyword,scanComplete:collector.searchAcceptance?.ok===true,year:Number(cutoff.slice(0,4)),cutoff,strictMedia:true});}
      catch(error){coverage={ok:false,reason:'DB_READBACK_FAILED',errorCode:error.code||'READBACK_ERROR'};}
    }
    const acceptanceVerified=dispatcher?.volume?coverage.ok===true:collector.searchAcceptance?.ok===true&&coverage.ok===true;
    if(coverage.ok&&coverage.unresolved&&['completed','completed_with_skips'].includes(taskState))taskState='completed_with_skips';
    if(["completed","completed_with_skips"].includes(taskState)&&!acceptanceVerified){
      taskState='incomplete';collector.error=coverage.reason||'SEARCH_END_UNVERIFIED';
    }
    let completed = ["completed","completed_with_skips"].includes(taskState) && (dispatcher?.volume ? coverage.ok===true : skipImport || importResult?.code === 0);
    const record = { workerId, runId, policyVersion: POLICY_VERSION, searchSummaries: collector.searchSummaries || [], taskId: task.id || null, topic: task.topic || null, keyword: task.keyword, projectName: task.projectName || null, collectComments: task.collectComments !== false, startedAt, finishedAt: now(), status: completed ? "completed" : taskState, exitCode: result.code, importExitCode: importResult?.code ?? null, outputDir: taskDir, stateDir, checkpointDb, posts: collector.posts ?? null, commentThreads: collector.commentThreads ?? null, error: collector.error || null };
    Object.assign(record,{collectionStatus,collectionError,mustStopNode:collectorFailure.stopNode,
      deadLetterNotes:collector.deadLetterNotes||0,collectionCompleteness:collector.collectionCompleteness||null,asrJobs:collector.asrJobs||null,
      searchAcceptance:collector.searchAcceptance||null,scopeAcceptance:collector.scopeAcceptance||null,coverage,
      firstFailureAt:collector.firstFailureAt||null,pageDiagnostics:collector.pageDiagnostics||null});
    if(completed && taskState==='completed_with_skips')record.status=taskState;
    if(noChange)record.stagnationEvidence=noChange;
    if(completed)record.accepted=coverage.ok;
    if (dispatcher) {
      const finishKind = completed ? "complete" : stopping ? "release" : taskState==="asr_review_required" ? "review" : ["login_required", "risk_controlled", "web_unavailable", "asr_deferred", "import_pending"].includes(taskState) ? "defer" : "fail";
      try {
        const confirmation = await dispatcher.finish(finishKind, record);
        record.redisConfirmed = volumeQueueConfirmed(confirmation) || !dispatcher.volume&&finishKind === "complete"&&['completed','completed_with_skips'].includes(confirmation?.status);
        if(dispatcher.volume&&(finishKind==='complete'||volumeQueueConfirmed(confirmation))){
          Object.assign(record,reconcileVolumeCompletion(record,confirmation));
          completed=record.redisConfirmed;taskState=record.status;
        }
        record.redisReleased = finishKind === "release";
        record.redisFailedHandled = !record.redisConfirmed&&(["fail","review","defer"].includes(finishKind)||dispatcher.volume&&finishKind==='complete');
        record.requiresHumanReview = finishKind === "review";
        record.redisDisposition = String(confirmation?.status || finishKind);
      } catch (error) {
        record.status = dispatcher.lost || error.code === "LEASE_LOST" ? "lease_lost" : "confirmation_failed";
        record.redisConfirmed = false;
        record.error = "Redis任务未能确认；数据已保留，服务端状态为准";
        await writeJsonAtomic(taskStatusPath, record);
        status.tasks.push(record);
        throw error;
      }
    }
    await writeJsonAtomic(taskStatusPath, record);
    status.tasks.push(record);
    await writeJsonAtomic(statusFile, { ...status, finishedAt: null });
    console.log(`[工作节点进度] ${workerId}：本机第${taskIndex + 1}词${dispatcher ? "" : `/${tasks.length}`}，关键词“${task.keyword}”状态=${record.status}`);
    if (stopSignalCount > 0 || await exists(stopFile)) {
      console.warn("[安全停止] 已请求安全停止；剩余关键词将在下次启动后继续");
      break;
    }
    // Do not let reset-once/P80 business completion hide the collector's node
    // stop decision. Data import and fenced queue disposition have finished.
    if (collectorFailure.stopNode) {
      console.warn(`[节点健康停止] ${workerId}：原采集状态=${collectionStatus}，业务状态=${record.status}；已保留原始故障，不领取下一词`);
      if (!collectorFailure.release) {
        throw Object.assign(new Error(`NODE_STOP_AFTER_COLLECTION_FAILURE：${collectionError || collectionStatus}；已停止领取后续任务`), {code:'COLLECTION_CONTEXT_FAILURE'});
      }
      break;
    }
    if (!completed) {
      console.warn(`[工作节点进度] 关键词“${task.keyword}”未通过验收（状态=${record.status}），数据已保全；Redis处置=${record.redisDisposition||'未使用Redis'}`);
      const failure = collectionFailurePolicy(record.error);
      if (failure.stopNode && !failure.release) {
        throw Object.assign(new Error(`NODE_STOP_AFTER_COLLECTION_FAILURE：${record.error || record.status}；已停止领取后续任务`), {code:'COLLECTION_CONTEXT_FAILURE'});
      }
      if (!dispatcher || ["login_required", "risk_controlled", "web_unavailable", "import_failed", "import_pending", "asr_deferred","asr_review_required"].includes(taskState)) break;
    }
    if (task.transitionDelaySeconds) await sleep(Number(task.transitionDelaySeconds) * 1000);
  }
  if(dispatcher && !skipImport && phase!=='posts' && !await exists(stopFile) && !status.tasks.some(task => task.mustStopNode || ['import_pending','import_failed','risk_controlled','login_required','web_unavailable','lease_lost','confirmation_failed'].includes(task.status))){
    await cooldown?.assertReady();
    status.authorPhase=await runAuthorPhase({root,stateRoot,runsRoot,workerId,stopFile,postDispatcher:dispatcher,cdpUrl:childEnv.XHS_CDP_URL,cooldown});
    console.log(`[采集阶段] 作者阶段=${status.authorPhase.status}，本机回填${status.authorPhase.completed}位作者`);
  }
} catch (error) {
  fatalError = error;
  if(['RATE_LIMIT_COOLDOWN_ACTIVE','COOLDOWN_MANUAL_REQUIRED'].includes(error.code))
    await fs.writeFile(stopFile,error.code,{encoding:'utf8',flag:'wx'}).catch(()=>{});
  console.warn(`[工作节点停止] ${error.code || "ERROR"}：${String(error.message || error).split("\n")[0]}`);
} finally {
  await stopCooldownMonitor?.();
  if(cooldown){
    try{status.cooldown=await cooldown.read();}
    catch(error){fatalError ||= error;}
  }
  if(cooldownMonitorError?.code==='COOLDOWN_STATE_UNAVAILABLE'||isStorageFull(cooldownMonitorError))
    fatalError ||= cooldownMonitorError;
  clearTimeout(runtimeTimer);
  await runtimeStopRequest;
  await dispatcher?.close({ stopped: stopSignalCount > 0 || await exists(stopFile) }).catch(error => {
    // A failed release/confirmation must take precedence over a benign cooldown.
    fatalError = error;
    console.warn(`[Redis收尾] ${error.code || "CONNECTION_ERROR"}；未确认的任务由租约到期回收`);
  });
  await remoteControl?.close(fatalError?'exit_unconfirmed':'collector_stopped').catch(()=>{fatalError ||= new Error('REMOTE_CONTROL_FINAL_ACK_UNAVAILABLE');});
  status.finishedAt = now();
  Object.assign(status, summarizeWorkerTasks(status.tasks));
  if (dispatcher?.lastStats) status.globalQueue = dispatcher.lastStats.counts;
  status.fatalError = fatalError ? String(fatalError.message || fatalError) : null;
  status.manualStopRequested = stopSignalCount > 0;
  status.exitCode = cooldownWorkerExit({fatalError,lost:dispatcher?.lost,status});
  status.cycleResumeEligible = status.exitCode === 0 && !status.manualStopRequested && !fatalError;
  status.exitDiagnosis={runtimeLimitObserved:Boolean(status.runtimeStop),manualStopRequested:status.manualStopRequested,
    fatalError:status.fatalError,taskStatuses:status.tasks.map(task=>({keyword:task.keyword,status:task.status,importExitCode:task.importExitCode})),
    automaticResumeEligible:status.cycleResumeEligible,lifecycleFile};
  await markLifecycle('worker_exit_decided',{exitCode:status.exitCode,...status.exitDiagnosis});
  console.log('[退出判定] '+JSON.stringify({workerId,exitCode:status.exitCode,
    runtimeLimitObserved:status.exitDiagnosis.runtimeLimitObserved,automaticResumeEligible:status.cycleResumeEligible,
    taskStatuses:status.tasks.map(task=>task.status),lifecycleFile}));
  await writeJsonAtomic(statusFile, status).catch(() => {});
  if (browserProcess && !browserProcess.killed) browserProcess.kill();
  // A request written during shutdown is still authoritative. The next
  // explicitly authorized launch, not this exiting worker, owns clearing it.
  await lockHandle?.close().catch(() => {});
  await fs.unlink(lockFile).catch(() => {});
  await cooldown?.close().catch(()=>{});
}
console.log(JSON.stringify({ workerId, mode, completed: status.completedCount, failed: status.failedCount, fatalError: fatalError ? String(fatalError.message || fatalError) : null, statusFile }, null, 2));
// Exit 5 is a deliberate lease-safety stop, not a collector/ASR crash.  The
// cycle supervisor must not reopen the browser until Redis has been restored.
const exitCode = cooldownWorkerExit({fatalError,lost:dispatcher?.lost,status});
process.exit(exitCode);
