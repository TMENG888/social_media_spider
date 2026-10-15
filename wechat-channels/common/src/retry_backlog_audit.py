"""Read-only backlog/candidate audit. Never resets a keyword or deletes MySQL rows."""
import argparse
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
import redis_task_queue as q
from retry_priority import iter_checkpoints, checkpoint_blocker


def audit(args, tasks):
    by_token = {q.safe_token(t['task_id']): t for t in tasks}
    keywords = {}
    unresolved_identities = set()
    for state_key, fp, cp in iter_checkpoints(q, args):
        token = state_key.split(':video-state:', 1)[1]
        task = by_token.get(token, {})
        stats = keywords.setdefault(token, {'taskId': task.get('task_id', token),
            'topic': task.get('topic'), 'keyword': task.get('keyword'),
            'knownCheckpoints': 0, 'unresolved': 0, 'linkedUnresolved': 0,
            'identitylessUnresolved': 0, 'states': Counter(), 'reasons': Counter()})
        stats['knownCheckpoints'] += 1
        stats['states'][cp.get('status') or 'unknown'] += 1
        reason = checkpoint_blocker(cp)
        if not reason:
            continue
        stats['unresolved'] += 1
        stats['reasons'][reason] += 1
        row = cp.get('row') or {}
        url = str(row.get('url') or cp.get('url') or '').strip()
        linked = url.startswith('https://weixin.qq.com/sph/')
        stats['linkedUnresolved'] += linked
        stats['identitylessUnresolved'] += not q.retry_payload_has_identity(cp)
        # Approximate across-keyword identity, not MySQL-authoritative video ID.
        identity = cp.get('article_key') or row.get('article_key') or (url if linked else None)
        if identity:
            unresolved_identities.add(str(identity))
    rows = list(keywords.values())
    for stats in rows:
        n, f = stats['knownCheckpoints'], stats['unresolved']
        stats['unresolvedRatio'] = round(f / n, 4)
        stats['savedLinkRatioAmongUnresolved'] = round(stats['linkedUnresolved'] / f, 4) if f else None
        stats['rescanCandidate'] = bool(n >= args.min_checkpoints and f / n >= args.rescan_ratio
                                        and stats['linkedUnresolved'] / max(1, f) < args.min_link_ratio)
        stats['recommendation'] = ('保留数据库与完成断点的关键词重扫候选；先恢复身份'
                                   if stats['rescanCandidate'] else '保存链接优先精准补采')
    rows.sort(key=lambda r: (-r['unresolved'], r['taskId']))
    return {'generatedAt': datetime.now().astimezone().isoformat(), 'readOnly': True,
        'thresholds': {'minCheckpoints': args.min_checkpoints, 'unresolvedRatio': args.rescan_ratio,
                       'savedLinkRatioBelow': args.min_link_ratio},
        'keywordsWithCheckpoints': len(rows), 'unresolvedCheckpoints': sum(r['unresolved'] for r in rows),
        'linkedUnresolved': sum(r['linkedUnresolved'] for r in rows),
        'identitylessUnresolved': sum(r['identitylessUnresolved'] for r in rows),
        'distinctKnownUnresolvedIdentities': len(unresolved_identities),
        'rescanCandidateKeywords': sum(r['rescanCandidate'] for r in rows), 'keywords': rows,
        'caveat': '跨关键词身份近似去重，缺身份不纳入distinct数；无标题断点可能是失败卡片占位。比例是已知断点口径，不是平台全量。链接存在不保证可访问。只提出重扫候选，不删除数据或重置任何任务。'}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--redis-url', default='redis://127.0.0.1:6379/0')
    p.add_argument('--password-file', type=Path, required=True)
    p.add_argument('--run-id', default='20260926-prod-01')
    p.add_argument('--queue', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--min-checkpoints', type=int, default=10)
    p.add_argument('--rescan-ratio', type=float, default=0.6)
    p.add_argument('--min-link-ratio', type=float, default=0.5)
    args = p.parse_args()
    args.redis_password = args.password_file.read_text(encoding='utf-8-sig').strip()
    args.prefix = 'wechat:channels:' + q.safe_token(args.run_id)
    tasks = q.flatten_queue(json.loads(args.queue.read_text(encoding='utf-8-sig')))
    report = audit(args, tasks)
    q.write_json(args.output, report)
    print(json.dumps({k: v for k, v in report.items() if k != 'keywords'}, ensure_ascii=False, indent=2))
    print(json.dumps(report['keywords'][:8], ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
