// Explicit operator recovery only; never called by the cycle restart path.
import fs from 'node:fs/promises';
import path from 'node:path';
import { randomUUID } from 'node:crypto';
import { fileURLToPath } from 'node:url';

const names = ['supervisor.stop', 'stop.requested'];
async function read(file) {
  try {
    const stat = await fs.lstat(file);
    if (!stat.isFile() || stat.isSymbolicLink() || stat.size > 4096)
      throw new Error('STOP_MARKER_UNSUPPORTED');
    return {raw: await fs.readFile(file, 'utf8'), mtime: stat.mtimeMs, ino: stat.ino};
  } catch (error) { if (error.code === 'ENOENT') return null; throw error; }
}
const same = (a, b) => a === b || !!a && !!b && a.raw === b.raw && a.mtime === b.mtime && a.ino === b.ino;
function alive(pid) {
  try { process.kill(pid, 0); return true; }
  catch (error) { return error.code !== 'ESRCH'; }
}
async function assertIdle(state, isAlive) {
  let lock;
  try { lock = JSON.parse(await fs.readFile(path.join(state, 'worker.lock'), 'utf8')); }
  catch (error) { if (error.code === 'ENOENT') return; throw new Error('WORKER_IDLE_UNCONFIRMED'); }
  if (!Number.isSafeInteger(lock.pid) || lock.pid <= 0) throw new Error('WORKER_IDLE_UNCONFIRMED');
  if (await isAlive(lock.pid)) throw new Error('WORKER_STILL_RUNNING');
}

export async function recoverManualStop({workerRoot, approvedBefore, approved = false,
  archiveRoot, inspectOnly = false, isAlive = alive, beforeMove, afterMove}) {
  const state = path.join(path.resolve(workerRoot), '.state');
  const cutoff = Date.parse(approvedBefore);
  if (!Number.isFinite(cutoff)) throw new Error('INVALID_APPROVAL_TIME');
  const snapshots = await Promise.all(names.map(name => read(path.join(state, name))));
  if (snapshots.every(value => !value)) return {ready: true, reason: 'no_stop_marker'};
  // JSON control, timer, storage, login and unknown requests are not manual stops.
  for (const value of snapshots.filter(Boolean)) {
    const match = /^manual stop (\d{4}-\d{2}-\d{2}T[^\r\n]+)\s*$/.exec(value.raw);
    const written = match ? Date.parse(match[1]) : NaN;
    if (!Number.isFinite(written)) throw new Error('NOT_A_MANUAL_STOP');
    if (value.mtime >= cutoff || written >= cutoff) throw new Error('NEW_STOP_REQUEST');
  }
  if (!approved) return {ready: false, reason: 'manual_stop_requires_explicit_resume'};
  await assertIdle(state, isAlive);
  if (inspectOnly) return {ready: true, reason: 'manual_stop_resume_validated'};
  if (!archiveRoot || path.parse(path.resolve(archiveRoot)).root.toLowerCase() === 'c:\\')
    throw new Error('NON_C_ARCHIVE_REQUIRED');
  const archive = path.join(archiveRoot, randomUUID());
  await fs.mkdir(archive, {recursive: true});
  // Copy before moving: an unavailable archive disk must leave all stops intact.
  for (let i = 0; i < names.length; i++) if (snapshots[i])
    await fs.writeFile(path.join(archive, names[i]), snapshots[i].raw, {flag: 'wx'});
  await beforeMove?.();
  await assertIdle(state, isAlive);
  const claims = [];
  try {
    for (let i = 0; i < names.length; i++) {
      for (let j = i; j < names.length; j++)
        if (!same(snapshots[j], await read(path.join(state, names[j])))) throw new Error('NEW_STOP_REQUEST');
      if (!snapshots[i]) continue;
      const file = path.join(state, names[i]);
      const claim = file + '.resume-claim-' + randomUUID();
      await fs.rename(file, claim);
      claims.push({file, claim, snapshot: snapshots[i]});
      await afterMove?.(i);
      if (!same(snapshots[i], await read(claim))) throw new Error('NEW_STOP_REQUEST');
      for (let j = 0; j <= i; j++)
        if (await read(path.join(state, names[j]))) throw new Error('NEW_STOP_REQUEST');
    }
    // New requests always win, even after both old flags have been moved.
    for (const name of names) if (await read(path.join(state, name))) throw new Error('NEW_STOP_REQUEST');
  } catch (error) {
    for (const {file, claim} of claims) {
      // Do not overwrite a concurrent new request. Keep any conflicting claim.
      try { await fs.link(claim, file); await fs.unlink(claim); }
      catch (restoreError) { if (restoreError.code !== 'EEXIST') throw restoreError; }
    }
    throw error;
  }
  for (const {claim} of claims) await fs.unlink(claim);
  return {ready: true, reason: 'old_manual_stop_archived', archive};
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const args = {};
  for (let i = 2; i < process.argv.length; i += 2) args[process.argv[i].replace(/^--/, '')] = process.argv[i + 1];
  try {
    const result = await recoverManualStop({workerRoot: args['worker-root'], approvedBefore: args.before,
      approved: args.approved === 'yes', inspectOnly: args.action === 'inspect', archiveRoot: args.archive});
    console.log('[Manual stop recovery] ' + JSON.stringify(result));
    if (!result.ready) console.error('人工停止标记仍有效。确认继续后，请运行本节点的“恢复采集任务.bat”；普通启动不会清除人工停止。');
    process.exitCode = result.ready ? 0 : 20;
  } catch (error) {
    console.error('[Manual stop recovery] ' + (['STOP_MARKER_UNSUPPORTED','WORKER_IDLE_UNCONFIRMED','WORKER_STILL_RUNNING',
      'INVALID_APPROVAL_TIME','NOT_A_MANUAL_STOP','NEW_STOP_REQUEST','NON_C_ARCHIVE_REQUIRED'].includes(error.message)
      ? error.message : 'RECOVERY_FAILED_STOP_PRESERVED'));
    process.exitCode = 20;
  }
}
