"""Operator command: snapshot one retry sweep, without resetting streams."""
import argparse
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0, str(Path(__file__).resolve().parent))
import redis_task_queue as q
from retry_round import start_round

def main():
    p = argparse.ArgumentParser()
    p.add_argument('--redis-url', default=os.environ.get('REDIS_URL', 'redis://127.0.0.1:6379/0'))
    p.add_argument('--run-id', default=os.environ.get('REDIS_RUN_ID', '20260926-prod-01'))
    p.add_argument('--credentials', type=Path, required=True)
    p.add_argument('--queue', type=Path, required=True)
    p.add_argument('--apply', action='store_true')
    a = p.parse_args()
    args = SimpleNamespace(redis_url=a.redis_url,
        redis_password=a.credentials.read_text(encoding='utf-8-sig').strip(),
        prefix='wechat:channels:' + q.safe_token(a.run_id), group='channels-workers')
    tasks = q.flatten_queue(json.loads(a.queue.read_text(encoding='utf-8-sig')))
    if not a.apply:
        print(json.dumps({'mode':'dry_run', 'tasks':len(tasks),
              'action':'Use --apply after all three workers have the new files and old workers are safely stopped.'}))
        return
    print(json.dumps(start_round(q, args, tasks), ensure_ascii=False, indent=2))

if __name__ == '__main__':
    main()
