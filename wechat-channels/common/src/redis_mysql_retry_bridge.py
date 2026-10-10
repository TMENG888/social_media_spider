"""Bind exact MySQL record/link to a Redis checkpoint, never by title alone."""
import argparse, hashlib, json, sys
from datetime import datetime
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from redis_task_queue import RedisConnection

def bind_record(cp, record):
    row=cp.get('row') or {}
    if record.get('平台')!='微信视频号' or cp.get('project')!=record.get('项目'):
        raise ValueError('Platform/project mismatch')
    if not cp.get('article_key') or cp['article_key']!=record.get('文章id'):
        raise ValueError('Exact article identity mismatch; title match is insufficient')
    if row.get('author_name') and row['author_name']!=record.get('作者名字'):
        raise ValueError('Author mismatch')
    import re
    link=record.get('文章链接') or ''
    if not re.fullmatch(r'https://weixin\.qq\.com/sph/[A-Za-z0-9]+',link):
        raise ValueError('Invalid canonical URL')
    return {**cp,'row':{**row,'url':link},'mysql_record_id':str(record['id']),
            'mysql_old_subtitle_hash':hashlib.sha256(str(record.get('文章视频内容') or '').encode()).hexdigest(),
            'mysql_link_verified_at':datetime.now().astimezone().isoformat()}

def confirm_commit(cp, receipt, record):
    new=bind_record(cp,record)
    text=str(record.get('文章视频内容') or '')
    digest=hashlib.sha256(text.encode()).hexdigest()
    if not text.strip() or not receipt.get('committed') or not receipt.get('readbackVerified'):
        raise ValueError('Verified nonempty database commit required')
    if str(receipt.get('id'))!=new['mysql_record_id'] or receipt.get('url')!=new['row']['url'] or receipt.get('subtitleHash')!=digest:
        raise ValueError('Database receipt identity/hash mismatch')
    complete=dict(cp.get('field_completeness') or {},asr=True)
    if any(complete.get(k) is not True for k in ('title','url','author','duration','comments')):
        raise ValueError('Other required video fields remain incomplete')
    new.update(row={**new['row'],'video_content':text},field_completeness=complete,
               status='completed',asr_status='completed',last_error=None,force_asr=False,
               subtitle_review_required=False,subtitle_incomplete_confirmed=False,
               mysql_commit_verified=receipt,updated_at=datetime.now().astimezone().isoformat())
    return new

LUA="""
if redis.call('HGET',KEYS[1],ARGV[1])~=ARGV[2] then return 0 end
redis.call('HSET',KEYS[2],ARGV[3],ARGV[2])
redis.call('HSET',KEYS[1],ARGV[1],ARGV[4])
return 1
"""
def main():
    p=argparse.ArgumentParser();p.add_argument('--record',type=Path,required=True)
    p.add_argument('--credentials',type=Path,required=True);p.add_argument('--state-key',required=True)
    p.add_argument('--fingerprint',required=True);p.add_argument('--report',type=Path,required=True)
    p.add_argument('--redis-url',default='redis://127.0.0.1:6379/0');p.add_argument('--apply',action='store_true')
    p.add_argument('--commit-receipt',type=Path)
    a=p.parse_args()
    if ':video-state:' not in a.state_key:raise ValueError('Expected video state hash')
    record=json.loads(a.record.read_text(encoding='utf-8-sig'))
    with RedisConnection(a.redis_url,a.credentials.read_text(encoding='utf-8-sig').strip()) as c:
        raw=c.command('HGET',a.state_key,a.fingerprint)
        if not raw:raise ValueError('Missing checkpoint')
        cp=json.loads(raw)
        if cp.get('status')=='running':raise ValueError('Video is running; do not modify')
        new=confirm_commit(cp,json.loads(a.commit_receipt.read_text(encoding='utf-8-sig')),record) if a.commit_receipt else bind_record(cp,record)
        result=None
        if a.apply:
            result=c.command('EVAL',LUA,2,a.state_key,a.state_key.split(':video-state:')[0]+':mysql-link-backup',
                             a.fingerprint,raw,a.state_key+'|'+a.fingerprint,
                             json.dumps(new,ensure_ascii=False))
            if result!=1:raise ValueError('Checkpoint changed concurrently; no replacement')
        report={'applied':bool(result),'dbId':new['mysql_record_id'],'url':new['row']['url'],
                'identityVerified':'exact article_key == MySQL 文章id','subtitleChanged':bool(a.commit_receipt),
                'checkpointBefore':cp,'checkpointAfter':new}
        a.report.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if not k.startswith('checkpoint')},ensure_ascii=False))
if __name__=='__main__':main()
