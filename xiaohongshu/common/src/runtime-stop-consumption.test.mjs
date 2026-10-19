import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import {pathToFileURL} from 'node:url';
const modulePath = process.env.XHS_TEST_RUNTIME_MODULE;
const {writeRuntimeStop, consumeRuntimeStop, consumeForQueue} = await import(modulePath ? pathToFileURL(modulePath) : new URL('./runtime-stop.mjs',import.meta.url));

async function fixture(t) {
  const dir = await fs.mkdtemp(path.join(os.tmpdir(), 'cycle-test-'));
  // Fixture directories intentionally remain on E: for reproducible evidence.
  const opt = {stopFile: path.join(dir, 'stop.requested'), supervisorStopFile: path.join(dir, 'supervisor.stop'),
    statusFile: path.join(dir, 'worker_status.json'), cycleId: 'cycle-1', workerId: 'worker-02'};
  const marker = await writeRuntimeStop({...opt, minutes: 55});
  const status = {workerId: opt.workerId, cycleId: opt.cycleId, exitCode: 0, fatalError: null,
    manualStopRequested: false, cycleResumeEligible: true, finishedAt: new Date().toISOString(),
    tasks: [{status: 'partial_stopped', preservationImported: true}], runtimeStop: marker};
  await fs.writeFile(opt.statusFile, JSON.stringify(status));
  return {dir, opt, marker, status};
}
const exists = file => fs.access(file).then(() => true, () => false);

test('normal owned runtime stop is consumed after clean final status', async t => {
  const {opt} = await fixture(t);
  assert.deepEqual(await consumeRuntimeStop(opt), {ready: true, reason: 'owned_runtime_stop_consumed'});
  assert.equal(await exists(opt.stopFile), false);
});
test('second cycle receives a distinct token and can consume independently', async t => {
  const {opt, status, marker} = await fixture(t);
  await consumeRuntimeStop(opt);
  const next = await writeRuntimeStop({...opt, cycleId: 'cycle-2', minutes: 46});
  assert.notEqual(next.token, marker.token);
  await fs.writeFile(opt.statusFile, JSON.stringify({...status, cycleId: 'cycle-2', runtimeStop: next}));
  assert.equal((await consumeRuntimeStop({...opt, cycleId: 'cycle-2'})).ready, true);
});
for (const replacement of ['manual stop 2026-10-18', 'SIGINT 2026-10-18', 'COOLDOWN_STATE_UNAVAILABLE',
  'RATE_LIMIT_COOLDOWN_ACTIVE', 'runtime limit 55 minutes 2026-10-18 00:59:00',
  JSON.stringify({source: 'redis_remote_control', commandId: 'stop-123'}),
  JSON.stringify({source: 'remote_control', reason: 'REMOTE_CONTROL_UNAVAILABLE'})]) {
  test('unknown/manual/legacy stop is retained: ' + replacement, async t => {
    const {opt} = await fixture(t);
    await fs.writeFile(opt.stopFile, replacement);
    assert.equal((await consumeRuntimeStop(opt)).ready, false);
    assert.equal(await fs.readFile(opt.stopFile, 'utf8'), replacement);
  });
}
test('runtime timeout never overwrites an existing human request', async t => {
  const {opt} = await fixture(t);
  await fs.writeFile(opt.stopFile, 'manual stop');
  assert.equal(await writeRuntimeStop({...opt, minutes: 45}), null);
  assert.equal(await fs.readFile(opt.stopFile, 'utf8'), 'manual stop');
});
test('supervisor stop blocks both runtime marker writing and consuming', async t => {
  const {opt} = await fixture(t);
  const original = await fs.readFile(opt.stopFile, 'utf8');
  await fs.writeFile(opt.supervisorStopFile, 'manual stop');
  assert.equal(await writeRuntimeStop({...opt, minutes: 45}), null);
  assert.equal((await consumeRuntimeStop(opt)).ready, false);
  assert.equal(await fs.readFile(opt.stopFile, 'utf8'), original);
});
for (const change of [{exitCode: 5}, {fatalError: 'MYSQL_IMPORT_FAILED'}, {manualStopRequested: true},
  {cycleResumeEligible: false}, {finishedAt: null}, {cycleId: 'different-cycle'},
  {tasks: [{status: 'import_pending'}]}, {tasks: [{status: 'login_required'}]},
  {tasks: [{status: 'lease_lost'}]}, {tasks: [{status: 'import_failed'}]},
  {tasks: [{status: 'partial_stopped', pendingImport: true}]},
  {tasks: [{status: 'partial_stopped', importExitCode: 75}]}]) {
  test('failed/unverified final status retains marker: ' + JSON.stringify(change), async t => {
    const {opt, status} = await fixture(t);
    await fs.writeFile(opt.statusFile, JSON.stringify({...status, ...change}));
    assert.equal((await consumeRuntimeStop(opt)).ready, false);
    assert.equal(await exists(opt.stopFile), true);
  });
}
test('missing status cannot authorize cleanup', async t => {
  const {opt} = await fixture(t); await fs.unlink(opt.statusFile);
  assert.equal((await consumeRuntimeStop(opt)).ready, false);
  assert.equal(await exists(opt.stopFile), true);
});
test('concurrent manual overwrite before rename is restored, not erased', async t => {
  const {opt} = await fixture(t);
  const result = await consumeRuntimeStop({...opt, afterRead: () => fs.writeFile(opt.stopFile, 'manual stop racing')});
  assert.equal(result.ready, false);
  assert.equal(await fs.readFile(opt.stopFile, 'utf8'), 'manual stop racing');
});
test('new stop written after rename remains authoritative', async t => {
  const {opt} = await fixture(t);
  const result = await consumeRuntimeStop({...opt, afterMove: () => fs.writeFile(opt.stopFile, 'new manual stop')});
  assert.equal(result.ready, false);
  assert.equal(await fs.readFile(opt.stopFile, 'utf8'), 'new manual stop');
});
test('concurrent replacement and a newer stop retain both pieces of evidence', async t => {
  const {opt, dir} = await fixture(t);
  const result = await consumeRuntimeStop({...opt,
    afterRead: () => fs.writeFile(opt.stopFile, 'first manual stop'),
    afterMove: () => fs.writeFile(opt.stopFile, 'second manual stop')});
  assert.equal(result.ready, false);
  assert.equal(await fs.readFile(opt.stopFile, 'utf8'), 'second manual stop');
  const evidence = (await fs.readdir(dir)).find(name => name.includes('.cycle-consumed-'));
  assert.ok(evidence);
  assert.equal(await fs.readFile(path.join(dir, evidence), 'utf8'), 'first manual stop');
});
test('supervisor stop arriving after rename prevents another cycle', async t => {
  const {opt} = await fixture(t);
  const result = await consumeRuntimeStop({...opt, afterMove: () => fs.writeFile(opt.supervisorStopFile, 'remote stop')});
  assert.equal(result.ready, false);
  assert.equal(await fs.readFile(opt.supervisorStopFile, 'utf8'), 'remote stop');
});
test('queue-specific state/runs roots are honored, other worker marker is untouched', async t => {
  const {dir, opt} = await fixture(t);
  const queueFile = path.join(dir, 'queue.json');
  await fs.writeFile(queueFile, JSON.stringify({workerId: opt.workerId, stateRoot: '.', runsRoot: '.'}));
  const unrelated = path.join(dir, 'other-worker'); await fs.mkdir(unrelated);
  await fs.writeFile(path.join(unrelated, 'stop.requested'), 'manual stop');
  assert.equal((await consumeForQueue({queueFile, commonRoot: dir,
    supervisorStopFile: opt.supervisorStopFile, cycleId: opt.cycleId})).ready, true);
  assert.equal(await fs.readFile(path.join(unrelated, 'stop.requested'), 'utf8'), 'manual stop');
});
