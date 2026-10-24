"""Real PowerShell worker + real importer, with isolated local collector/DB doubles.

No crawler UI, Redis endpoint or MySQL socket is used. Temp roots are controlled
by the test runner's TEMP/TMP (E: in the acceptance run).
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

COMMON = Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.name == 'nt' and shutil.which('powershell.exe'), 'Windows PowerShell required')
class StandbyWorkerTests(unittest.TestCase):
    def exercise(self, mode, *, previous=False, asr=False):
        with tempfile.TemporaryDirectory(prefix='channels-standby-worker-') as folder:
            root = Path(folder)
            common = root / 'common'
            src = common / 'src'
            src.mkdir(parents=True)
            worker = root / 'worker-02'
            worker.mkdir()
            for name in ('run-worker.ps1', 'run-asr-backfill.ps1', 'worker-recovery.ps1'):
                shutil.copy2(COMMON / name, common / name)
            shutil.copy2(COMMON / 'src/mysql-defaults.json', src / 'mysql-defaults.json')
            (common / 'check-env.ps1').write_text("'{\"ok\":true}'", encoding='ascii')
            (common / 'collector_config.json').write_text(json.dumps({'jitter_enabled': False}), encoding='ascii')
            (root / 'keywords.txt').write_text('first\nsecond', encoding='ascii')
            queue = {'cutoff': '2026-01-01', 'tasks': [{'id': 'fixture', 'name': 'fixture',
                'keywordsFile': 'keywords.txt', 'keywordAllowList': ['first', 'second'], 'collectComments': False}]}
            (worker / 'task-queue.json').write_text(json.dumps(queue), encoding='ascii')
            # Only this proxy executes the production wrapper, with the explicit
            # no-socket bootstrap from test_mysql_transport_cli.mjs.
            wrapper = str(COMMON / 'src/mysql-import-retry.mjs')
            bootstrap = (COMMON / 'tests/fixtures/mysql-transport.mjs').as_uri()
            (src / 'mysql-import-retry.mjs').write_text(
                "import {spawnSync} from 'node:child_process';\n"
                f"const r=spawnSync(process.execPath,[{json.dumps(wrapper)},...process.argv.slice(2)],"
                "{stdio:'inherit',windowsHide:true,env:{...process.env,NODE_OPTIONS:"
                f"{json.dumps('--import=' + bootstrap)}" + "}});process.exit(r.status??2);", encoding='ascii')
            (src / 'mysql-check.mjs').write_text('// local preflight fixture; never opens a socket\n', encoding='ascii')
            (src / 'channels_pc_collector.py').write_text('''import sys,pathlib,os,json
a=sys.argv
def value(k): return a[a.index(k)+1]
root=pathlib.Path(os.environ['CHANNELS_MYSQL_TEST_ROOT'])
if a[1]=='export-ods':
 row={'文章链接':'https://weixin.qq.com/sph/'+value('--keyword'),'文章id':value('--keyword'),'平台':'微信视频号','项目':'fixture'}
 pathlib.Path(value('--output-dir'),'ods_social_media_post_channels.jsonl').write_text(json.dumps(row)+'\\n',encoding='utf-8')
elif a[1]=='collect-live':
 with (root/'collected.txt').open('a') as f: f.write(value('--keyword')+'\\n')
 pathlib.Path(value('--state-db')).write_bytes(b'durable-fixture-checkpoint')
elif a[1]=='checkpoint-status':
 print(json.dumps({'notes':[],'pending':1,'completed':0}))
''', encoding='utf-8')
            (src / 'channels_browser_enricher.mjs').write_text(
                "import fs from 'node:fs';fs.writeFileSync(process.argv[3],'');", encoding='ascii')
            (src / 'channels_ods_postprocess.mjs').write_text(
                "import fs from 'node:fs';fs.copyFileSync(process.argv[2],process.argv[4]);", encoding='ascii')
            state_dir = worker / '.state/redis-runs/fixture'
            state_dir.mkdir(parents=True)
            state_db = state_dir / 'fixture.sqlite'
            if previous or asr:
                state_db.write_bytes(b'durable-fixture-checkpoint')
            if previous:
                old = worker / 'runs/redis-runs/fixture/fixture/first'
                old.mkdir(parents=True)
                (old / 'keyword_status.json').write_text('{"status":"failed"}', encoding='ascii')
            env = {**os.environ, 'WECHAT_WORKER_ROOT': str(worker),
                'WECHAT_PYTHON': str(COMMON / 'runtime/python/python.exe'),
                'WECHAT_NODE': str(COMMON / 'runtime/node/node.exe'), 'MYSQL_ENABLED': '1',
                'MYSQL_USER': 'fixture', 'MYSQL_PASSWORD': 'fixture-only',
                'CHANNELS_MYSQL_TEST_ROOT': str(root), 'CHANNELS_MYSQL_TEST_MODE': mode,
                'CHANNELS_MYSQL_STANDBY_MINUTES': '3', 'WECHAT_REDIS_STATE_SCOPE': 'fixture',
                'WECHAT_RECOLLECT_ONCE': '1'}
            for key in ('WECHAT_QUEUE_FILE', 'NODE_OPTIONS', 'WECHAT_REDIS_VIDEO_FINGERPRINT', 'WECHAT_REDIS_VIDEO_ARTICLE_KEY'):
                env.pop(key, None)
            script = 'run-asr-backfill.ps1' if asr else 'run-worker.ps1'
            result = subprocess.run(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass',
                '-File', str(common / script)], env=env, capture_output=True, timeout=30,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            output = result.stdout.decode(errors='replace') + result.stderr.decode(errors='replace')
            self.assertNotIn('fixture-only SQL/password', output)
            database = json.loads((root / 'fake-database.json').read_text(encoding='utf-8'))
            self.assertEqual(database['active'], 0)
            self.assertIn('mysql_import_standby_started', output)
            self.assertEqual(state_db.read_bytes(), b'durable-fixture-checkpoint')
            collected_file = root / 'collected.txt'
            collected = collected_file.read_text().splitlines() if collected_file.exists() else []
            if asr:
                report = json.loads((worker / '.state/asr_backfill_status.json').read_text(encoding='utf-8-sig'))
                rows = report['keywords']
            else:
                report = json.loads((worker / '.state/worker_status.json').read_text(encoding='utf-8-sig'))
                rows = [k for t in report['tasks'] for k in t['keywords']]
            if mode == 'exhausted':
                self.assertEqual(result.returncode, 75, output)
                self.assertEqual(database['connections'], 5, output)  # no second salvage standby
                self.assertEqual(database['commits'], 0)
                self.assertEqual([k['keyword'] for k in rows], ['first'])
                self.assertEqual(collected, [] if previous else ['first'])
                if not asr:
                    self.assertEqual(rows[0]['mysql']['errorCode'], 'ENOTFOUND')
                    self.assertEqual(rows[0]['mysql']['commitState'], 'not_attempted')
            else:
                self.assertEqual(result.returncode, 0, output)
                self.assertEqual(collected, ['first', 'second'])
                self.assertTrue(all(k['mysql']['status'] == 'success' for k in rows))

    def test_fresh_worker_standby_exhaustion_does_not_start_next_keyword(self):
        self.exercise('exhausted')

    def test_interrupted_recovery_does_not_open_second_standby_or_replay_collection(self):
        self.exercise('exhausted', previous=True)

    def test_asr_backfill_import_exhaustion_does_not_start_next_keyword(self):
        self.exercise('exhausted', asr=True)

    def test_network_recovery_imports_then_allows_normal_next_keyword(self):
        self.exercise('standby_recover')


if __name__ == '__main__':
    unittest.main()
