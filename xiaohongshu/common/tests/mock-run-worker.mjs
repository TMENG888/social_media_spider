import fs from 'node:fs/promises';
import path from 'node:path';
import {writeRuntimeStop} from './runtime-stop.mjs';
const args = {};
for (let i = 2; i < process.argv.length; i += 2) args[process.argv[i].replace(/^--/, '')] = process.argv[i + 1];
if (args.mode === 'check') process.exit(0);
const queue = JSON.parse(await fs.readFile(args.queue, 'utf8'));
const state = path.resolve(path.dirname(args.queue), queue.stateRoot);
const runs = path.resolve(path.dirname(args.queue), queue.runsRoot);
await fs.mkdir(runs, {recursive: true});
const stopFile = path.join(state, 'stop.requested');
if (await fs.access(stopFile).then(() => true, () => false)) {
  console.error('FIXTURE_STALE_STOP_PREVENTED_NEXT_ROUND'); process.exit(1);
}
const countFile = path.join(state, 'fixture-round-count.json');
const count = Number(await fs.readFile(countFile, 'utf8').catch(() => '0')) + 1;
await fs.writeFile(countFile, JSON.stringify(count));
const scenario = process.env.XHS_TEST_SCENARIO;
let marker = null;
if (count === 1 && scenario !== 'no-timeout') {
  marker = await writeRuntimeStop({stopFile, supervisorStopFile: path.join(state, 'supervisor.stop'),
    cycleId: args['cycle-id'], workerId: queue.workerId, minutes: Number(args['max-runtime-minutes'])});
  if (scenario === 'legacy-stop') await fs.writeFile(stopFile, 'runtime limit 55 minutes 2026-10-18 00:59:00');
  if (scenario === 'manual-before-rest') await fs.writeFile(stopFile, 'manual stop fixture');
}
const failure = scenario === 'lease-failed' ? 5 : scenario === 'import-failed' ? 1 : 0;
await fs.writeFile(path.join(runs, 'worker_status.json'), JSON.stringify({workerId: queue.workerId,
  cycleId: args['cycle-id'], finishedAt: new Date().toISOString(), exitCode: failure,
  fatalError: failure ? 'FIXTURE_FAILURE' : null, manualStopRequested: false,
  cycleResumeEligible: failure === 0, runtimeStop: marker,
  tasks: [{status: failure ? 'import_failed' : count === 1 ? 'partial_stopped' : 'completed', redisReleased: true}]}));
await fs.writeFile(path.join(state, 'redis_queue_status.json'), JSON.stringify({counts: {
  failed: 0, pending: count === 1 ? 1 : 0, leased: 0}}));
console.log('FIXTURE_ROUND_COMPLETED ' + count);
process.exit(failure);
