// Local cycle bookkeeping only. No Redis, browser or database access.
import fs from 'node:fs/promises';
import path from 'node:path';
import {randomUUID} from 'node:crypto';
import {fileURLToPath} from 'node:url';

const present = file => fs.lstat(file).then(() => true, error => {
  if (error.code === 'ENOENT') return false;
  throw error;
});
const blocked = reason => ({ready: false, reason});
const badTaskStates = new Set(['failed', 'partial_error', 'import_failed', 'import_pending',
  'login_required', 'risk_controlled', 'web_unavailable', 'lease_lost', 'confirmation_failed']);

export async function writeRuntimeStop({stopFile, supervisorStopFile, cycleId, workerId, minutes}) {
  if (supervisorStopFile && await present(supervisorStopFile)) return null;
  const marker = {schemaVersion: 1, source: 'cycle_runtime_limit', cycleId,
    workerId, pid: process.pid, token: randomUUID(), minutes, createdAt: new Date().toISOString()};
  let handle;
  try { handle = await fs.open(stopFile, 'wx'); }
  catch (error) { if (error.code === 'EEXIST') return null; throw error; }
  try { await handle.writeFile(JSON.stringify(marker) + '\n', 'utf8'); await handle.sync(); }
  finally { await handle.close(); }
  return marker;
}

async function restoreClaim(claim, stopFile) {
  // Exclusive hard-link creation cannot replace a newer stop request.
  try { await fs.link(claim, stopFile); await fs.unlink(claim); }
  catch (error) { if (error.code !== 'EEXIST') throw error; }
}

// Startup recovery is deliberately separate from clean-cycle consumption.
// Archiving a dead process's timer does NOT accept its tasks or authorize an
// automatic restart after failure. Call only after acquiring the worker lock.
export async function recoverOrphanRuntimeStop({stopFile, supervisorStopFile,
  workerId, cycleId, isProcessAlive = processIsAlive, afterRead, afterMove}) {
  if (supervisorStopFile && await present(supervisorStopFile)) return blocked('supervisor_stop');
  if (!await present(stopFile)) return {ready: true, reason: 'no_stop_marker'};
  const stat = await fs.lstat(stopFile);
  if (!stat.isFile() || stat.isSymbolicLink() || stat.size > 16384)
    return blocked('unknown_stop_marker');
  const raw = await fs.readFile(stopFile, 'utf8');
  let marker;
  try { marker = JSON.parse(raw); }
  catch { return blocked('unknown_stop_marker'); }
  const created = Date.parse(marker?.createdAt);
  if (marker?.schemaVersion !== 1 || marker.source !== 'cycle_runtime_limit'
      || marker.workerId !== workerId || !/^[0-9a-f]{32}$/i.test(marker.cycleId || '')
      || marker.cycleId === cycleId || !Number.isSafeInteger(marker.pid) || marker.pid <= 0
      || !/^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i.test(marker.token || '')
      || !Number.isFinite(marker.minutes) || marker.minutes <= 0 || marker.minutes > 10080
      || typeof marker.createdAt !== 'string' || !Number.isFinite(created) || created > Date.now())
    return blocked('unverified_runtime_stop');
  // Permission errors, PID reuse and an uncertain process state all fail closed.
  if (await isProcessAlive(marker.pid)) return blocked('runtime_stop_owner_alive');
  await afterRead?.();
  if (supervisorStopFile && await present(supervisorStopFile)) return blocked('supervisor_stop');
  if (await isProcessAlive(marker.pid)) return blocked('runtime_stop_owner_alive');
  const archive = stopFile + '.runtime-archived-' + randomUUID() + '.json';
  try { await fs.rename(stopFile, archive); }
  catch (error) { if (error.code === 'ENOENT') return blocked('stop_marker_changed'); throw error; }
  try {
    await afterMove?.();
    const moved = await fs.lstat(archive);
    if (!moved.isFile() || moved.isSymbolicLink() || await fs.readFile(archive, 'utf8') !== raw) {
      await restoreClaim(archive, stopFile);
      return blocked('stop_marker_changed');
    }
  } catch (error) { await restoreClaim(archive, stopFile); throw error; }
  // Keep the original evidence. A human/remote request racing with recovery wins.
  if (await present(stopFile) || supervisorStopFile && await present(supervisorStopFile))
    return {ready: false, reason: 'new_stop_request', archive};
  return {ready: true, reason: 'orphan_runtime_stop_archived', archive,
    previousCycleId: marker.cycleId, previousPid: marker.pid, createdAt: marker.createdAt};
}

function processIsAlive(pid) {
  try { process.kill(pid, 0); return true; }
  catch (error) { return error.code !== 'ESRCH'; }
}

export async function consumeRuntimeStop({stopFile, supervisorStopFile, statusFile, cycleId,
  workerId, afterRead, afterMove}) {
  if (supervisorStopFile && await present(supervisorStopFile)) return blocked('supervisor_stop');
  if (!await present(stopFile)) return {ready: true, reason: 'no_stop_marker'};
  const stat = await fs.lstat(stopFile);
  if (!stat.isFile() || stat.isSymbolicLink() || stat.size > 16384) return blocked('unknown_stop_marker');
  const raw = await fs.readFile(stopFile, 'utf8');
  let marker, status;
  try { marker = JSON.parse(raw); status = JSON.parse(await fs.readFile(statusFile, 'utf8')); }
  catch (error) {
    if (error instanceof SyntaxError || error.code === 'ENOENT') return blocked('unverified_stop_marker');
    throw error;
  }
  if (marker?.schemaVersion !== 1 || marker.source !== 'cycle_runtime_limit'
      || !cycleId || marker.cycleId !== cycleId || marker.workerId !== workerId
      || !marker.token || !Number.isInteger(marker.pid)
      || status.cycleId !== cycleId || status.workerId !== workerId
      || status.exitCode !== 0 || status.fatalError || status.manualStopRequested
      || status.cycleResumeEligible !== true || !status.finishedAt
      || !Array.isArray(status.tasks) || status.tasks.some(task => badTaskStates.has(task.status)
        || task.pendingImport === true || task.importExitCode != null && task.importExitCode !== 0)
      || raw.trim() !== JSON.stringify(status.runtimeStop)) return blocked('unverified_stop_marker');
  await afterRead?.();
  if (supervisorStopFile && await present(supervisorStopFile)) return blocked('supervisor_stop');
  const claim = stopFile + '.cycle-consumed-' + randomUUID();
  try { await fs.rename(stopFile, claim); }
  catch (error) { if (error.code === 'ENOENT') return blocked('stop_marker_changed'); throw error; }
  try {
    await afterMove?.();
    const claimedStat = await fs.lstat(claim);
    if (!claimedStat.isFile() || claimedStat.isSymbolicLink()
        || await fs.readFile(claim, 'utf8') !== raw) {
      await restoreClaim(claim, stopFile);
      return blocked('stop_marker_changed');
    }
  } catch (error) { await restoreClaim(claim, stopFile); throw error; }
  await fs.unlink(claim);
  // A request written while the owned marker was consumed is still authoritative.
  if (await present(stopFile) || supervisorStopFile && await present(supervisorStopFile))
    return blocked('new_stop_request');
  return {ready: true, reason: 'owned_runtime_stop_consumed'};
}

export async function consumeForQueue({queueFile, commonRoot, supervisorStopFile, cycleId}) {
  const queue = JSON.parse((await fs.readFile(queueFile, 'utf8')).replace(/^\uFEFF/, ''));
  const queueDir = path.dirname(path.resolve(queueFile));
  const stateRoot = path.resolve(queueDir, queue.stateRoot || path.join(commonRoot, '.state', queue.workerId));
  const runsRoot = path.resolve(queueDir, queue.runsRoot || path.join(commonRoot, 'runs', queue.workerId));
  return consumeRuntimeStop({stopFile: path.join(stateRoot, 'stop.requested'), supervisorStopFile,
    statusFile: path.join(runsRoot, 'worker_status.json'), cycleId, workerId: queue.workerId});
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const args = {};
  for (let i = 2; i < process.argv.length; i += 2) args[process.argv[i].replace(/^--/, '')] = process.argv[i + 1];
  try {
    const result = await consumeForQueue({queueFile: args.queue, commonRoot: args.root,
      supervisorStopFile: args['supervisor-stop'], cycleId: args['cycle-id']});
    console.log('[Cycle stop] ' + result.reason);
    process.exitCode = result.ready ? 0 : 20;
  } catch {
    console.error('[Cycle stop] Local stop-state verification failed; no next cycle allowed.');
    process.exitCode = 1;
  }
}
