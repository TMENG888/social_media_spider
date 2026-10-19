"""Durable candidate review: rejected ASR never overwrites a committed value."""
import json
import os
import re
from datetime import datetime
from transcript_quality import transcript_artifact

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


def has_untrusted_transcript(text):
    if os.environ.get('SOCIAL_VOLUME_ENABLED') == '1':
        return False
    return has_internal_prompt(text) or bool(transcript_artifact(text))


def checkpoint_repair_reason(checkpoint, *, collect_comments=True):
    """Known defects invalidate a terminal cache, not the retained evidence.

    This is a repair admission check, NOT database or annual-scan acceptance.
    Legacy records without a row still need the independent SQL verifier.
    Explicit unresolved dispositions are never silently reopened here.
    """
    cp = checkpoint or {}
    if cp.get('status') in {'dead_letter', 'skipped_unresolved'}:
        return None
    row = cp.get('row') or {}
    if not isinstance(row, dict):
        return 'DETAIL_CHECKPOINT_INVALID'
    if has_untrusted_transcript(row.get('video_content')):
        return 'ASR_QUALITY_UNTRUSTED_TRANSCRIPT'
    volume_mode = os.environ.get('SOCIAL_VOLUME_ENABLED') == '1'
    if not volume_mode and (cp.get('subtitle_review_required') or cp.get('asr_status') in {'review', 'partial_review'}):
        return 'ASR_QUALITY_REVIEW_REQUIRED'
    fields = cp.get('field_completeness') or {}
    if not isinstance(fields, dict):
        return 'DETAIL_FIELD_COMPLETENESS_INVALID'
    if not volume_mode and 'asr' in fields and fields['asr'] is not True:
        return 'ASR_QUALITY_INCOMPLETE_TRANSCRIPT'
    if any(value is not True for field, value in fields.items()
           if (field != 'comments' or collect_comments) and (field != 'asr' or not volume_mode)):
        return 'DETAIL_INCOMPLETE_FIELDS'
    if row and cp.get('status') in {'completed', 'no_content', 'not_applicable'}:
        if any(not str(row.get(field) or '').strip() for field in ('title', 'url', 'author_name')):
            return 'DETAIL_INCOMPLETE_IDENTITY'
        try:
            import math
            duration = float(row.get('video_duration') or 0)
            if not math.isfinite(duration) or duration <= 0:
                return 'DETAIL_INCOMPLETE_DURATION'
        except (TypeError, ValueError):
            return 'DETAIL_INCOMPLETE_DURATION'
        if not volume_mode and cp.get('status') == 'completed' and (
                cp.get('asr_status') != 'completed' or not str(row.get('video_content') or '').strip()):
            return 'ASR_QUALITY_INCOMPLETE_TRANSCRIPT'
    return None

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
                str(checkpoint_repair_reason(cp) or '').startswith('ASR_QUALITY_') or
                has_untrusted_transcript((cp.get('row') or {}).get('video_content')) or
                re.search(r'污染|pollut', str(cp.get('last_error') or ''), re.I))
