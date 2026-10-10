"""Durable candidate review: rejected ASR never overwrites a committed value."""
import json
import re
from datetime import datetime

def init_review_tables(db):
    db.execute('''CREATE TABLE IF NOT EXISTS asr_candidate (
        id INTEGER PRIMARY KEY AUTOINCREMENT, article_key TEXT, keyword TEXT,
        text TEXT, status TEXT, reason TEXT, created_at TEXT)''')
    db.execute('''CREATE TABLE IF NOT EXISTS subtitle_backup (
        id INTEGER PRIMARY KEY AUTOINCREMENT, article_key TEXT, keyword TEXT,
        old_text TEXT, reason TEXT, created_at TEXT)''')
    db.commit()

def has_internal_prompt(text):
    return bool(re.search(r'全国地产设计产品力监测|北京臻澐项目口碑(?:监测|采集)', text or ''))

def stage_candidate(db, article_key, keyword, text, *, approved, reason):
    init_review_tables(db)
    now = datetime.now().isoformat(timespec='seconds')
    db.execute('INSERT INTO asr_candidate(article_key,keyword,text,status,reason,created_at) VALUES(?,?,?,?,?,?)',
               (article_key, keyword, text, 'approved' if approved else 'review', reason, now))
    if approved and text:
        old = db.execute('SELECT video_content FROM captured_article WHERE article_key=? AND keyword=?',
                         (article_key, keyword)).fetchone()
        if old and old[0] and old[0] != text:
            db.execute('INSERT INTO subtitle_backup(article_key,keyword,old_text,reason,created_at) VALUES(?,?,?,?,?)',
                       (article_key, keyword, old[0], reason or 'approved ASR replacement', now))
    db.commit()

def force_retranscribe(config, checkpoint=None):
    cp = checkpoint or {}
    return bool(config.get('force_asr') or cp.get('force_asr') or
                has_internal_prompt((cp.get('row') or {}).get('video_content')) or
                re.search(r'污染|pollut', str(cp.get('last_error') or ''), re.I))
