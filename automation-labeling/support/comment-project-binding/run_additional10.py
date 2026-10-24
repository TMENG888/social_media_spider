"""Ten NEW review cases from the remaining explicitly non-ad cached comments.

This is a project-attribution test, not ten newly generated sources or a full
tag-quality retest. Successful old slices/tags and first-pilot work are reused.
"""
import argparse, copy, hashlib, json, os, sys, time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
sys.dont_write_bytecode = True
sys.stdout.reconfigure(encoding='utf-8')
import comment_pipeline_v105 as pipeline
q = pipeline.q
WORK = Path(__file__).resolve().parent / 'additional10'
OUT = Path('E:/Codex/outputs/20261020_评论项目归属_新增10条测试')
BASE = Path('E:/Codex/outputs/20261020_587条评论项目归属复查/587条库存_10条项目复核修正版.json')
CASES = [
 ('T2-C-7963753211120749815', '未点名，旧标签跨安澜与熙瑞'),
 ('T2-C-7963753211120747227', '未点名，旧项目与父文主讲项目不同'),
 ('T2-C-7963753211120750640', '别墅评论，检查是否误继承臻澐'),
 ('T2-C-7963753211120750321', '明确比较臻澐与海晏，标签分别归属'),
 ('T2-C-1238029', '未点名，双项目父文的物业费指代'),
 ('T2-C-7963753211120747308', '只提保利品牌，不能独立锁定楼盘'),
 ('T2-C-1237906', '安澜别名直接归属'),
 ('T2-C-7963753211120747228', '未点名，父文唯一主讲楼盘'),
 ('T2-C-7963753211120752007', '旧结果跨臻澐海晏，父文唯一主讲楼盘'),
 ('T2-C-7963753211120747187', '西冉地块与熙瑞近邻项目区分')]
REPAIR_IDS={'T2-C-7963753211120747187'}


def prepare():
    WORK.mkdir(parents=True, exist_ok=True)
    pipeline.configure(OUT)
    base = q.p.read(BASE)
    by = {s['record_id']: s for s in base['sources']}
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'legacy-runtime'))
    import collect_effective_sources as c
    reviews = c.source_decisions()
    ad_proofs = {}
    for rid, _ in CASES:
        s = by[rid]
        assert s['kind'] == '评论' and not s.get('project_attribution_revision'), 'Do not repeat first pilot'
        decision = reviews[s['document']['source_id']]
        assert decision['is_ad'] == '否'
        assert decision['text_sha256'] == hashlib.sha256(s['document']['text'].encode()).hexdigest()
        ad_proofs[rid] = decision
    plan = {'base_inventory': q.reference(BASE), 'base_source_count': len(base['sources']),
            'unreviewed_comments_before': sum(s['kind'] == '评论' and not s.get('project_attribution_revision') for s in base['sources']),
            'items': [{'record_id': rid, 'stratum': st, 'own_ad_decision': ad_proofs[rid]} for rid, st in CASES],
            'scope': 'project_binding_only_reuse_existing_slices_and_tags', 'new_source_count': 0,
            'entrypoint': q.reference(pipeline.__file__), 'policy': q.reference(q.__file__)}
    q.save(WORK / 'plan.json', plan)
    return base, by, plan


def run():
    base, by, plan = prepare()
    lock = WORK / 'instance.lock'
    fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    os.write(fd, str(os.getpid()).encode()); os.close(fd)
    before = q.sha(BASE)
    q.p.OUT = OUT
    q.p.STOP = WORK / 'soft_stop.request'
    events, failures = [], []
    started = time.time()
    def status(state):
        value = {'state': state, 'pid': os.getpid(), 'started_at': started, 'updated_at': time.time(),
                 'target': 10, 'completed': len(events), 'events': events, 'failures': failures,
                 'concurrency_ceiling': 4, 'old_chain_not_resumed': True}
        q.save(WORK / 'run_status.json', value)
    try:
        runner = q.p.configure_runner(4, True)
        q.save(WORK / 'launcher_identity.json', {'pid': os.getpid(), 'started_at': started,
              'script': __file__, 'script_sha256': q.sha(__file__), 'model': runner.model,
              'pipeline': q.reference(pipeline.__file__), 'credential_saved': False})
        status('running_additional10_project_binding')
        def one(rid):
            revised, proof = pipeline.process_saved(by[rid], runner, force_revision=rid in REPAIR_IDS)
            assert proof and proof['verification']['passed']
            return {'record_id': rid, 'state': revised['state'], **proof}
        with ThreadPoolExecutor(max_workers=4) as pool:
            tasks = {pool.submit(one, rid): rid for rid, _ in CASES}
            for f in as_completed(tasks):
                rid = tasks[f]
                try: events.append(f.result())
                except Exception as e: failures.append({'record_id': rid, 'error_type': type(e).__name__, 'error': str(e)})
                status('running_additional10_project_binding')
        assert q.sha(BASE) == before
        status('stages_saved_needs_review' if not failures else 'incomplete_successes_preserved')
        print(json.dumps({'completed': len(events), 'failures': failures, 'elapsed_seconds': time.time()-started}, ensure_ascii=False))
    finally:
        lock.unlink()


if __name__ == '__main__':
    a = argparse.ArgumentParser(); a.add_argument('--run', action='store_true'); args = a.parse_args()
    if args.run: run()
    else:
        _, _, plan = prepare()
        print(json.dumps({k:v for k,v in plan.items() if k!='items'}, ensure_ascii=False))
