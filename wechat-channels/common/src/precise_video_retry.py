"""URL-first exact retry. UI adapters are supplied by the production collector."""
import json
import time
from dataclasses import fields

def open_saved_video(c, url, config):
    if not c.is_valid_channels_share_url(url):
        raise ValueError('Not a trusted WeChat Channels URL')
    web = c.get_search_window(wait_seconds=4)
    web.set_focus()
    bounds = web.rectangle()
    def header_edits():
        return [e for e in web.descendants(control_type='Edit')
                if e.rectangle().top < bounds.top + 80]
    def inside(element):
        r = element.rectangle()
        return (r.right > r.left and r.bottom > r.top and
                bounds.left <= r.left < r.right <= bounds.right and
                bounds.top <= r.top < r.bottom <= bounds.bottom)
    edits = header_edits()
    if len(edits) != 1:
        raise RuntimeError('Cannot uniquely locate WeChat URL edit')
    if not inside(edits[0]):
        # The collapsed address edit remains in UIA but is outside the window.
        # The magnifier is immediately left of the native minimize button;
        # derive its location from that button, not the display resolution.
        anchors = [b for b in web.descendants(control_type='Button')
                   if b.window_text() == '最小化' and inside(b)
                   and b.rectangle().top < bounds.top + 80]
        if len(anchors) != 1:
            raise RuntimeError('Cannot safely expand collapsed URL edit')
        r = anchors[0].rectangle()
        width = r.right - r.left
        x, y = r.left - width // 2, (r.top + r.bottom) // 2
        if not bounds.left <= x < bounds.right:
            raise RuntimeError('URL expansion anchor is outside window')
        c.mouse.click(coords=(x, y))
        c.wait_for(lambda: len(header_edits()) == 1 and inside(header_edits()[0]), timeout=3)
        edits = header_edits()
        if len(edits) != 1 or not inside(edits[0]):
            raise RuntimeError('URL edit did not expand into visible window')
    # Use the actual exposed edit rather than screen-resolution coordinates.
    edits[0].click_input()
    c.set_clipboard(url)
    c.keyboard.send_keys('^a^v{ENTER}', pause=0.05)
    c.wait_for(lambda: c.has_video_detail_window(), timeout=12)
    surface = c.get_video_detail_window(wait_seconds=6)
    c.pause_active_video_if_running(surface)
    return surface

def verify_target(c, surface, cp):
    row = cp.get('row') or {}
    records = c.active_video_records(surface)
    details = c.parse_article_details(records)
    title = row.get('title') or cp.get('title')
    author = row.get('author_name') or cp.get('author_name')
    stored_duration = row.get('video_duration') or cp.get('video_duration')
    if not title:
        if not author or not stored_duration:
            raise RuntimeError('identity_recovery_required: URL record lacks title and corroborating author/duration')
        # A saved canonical URL is an identity; restore metadata from its
        # visible first item, never invent identity from a numeric list index.
        candidates = [v for v, kind, cls in records
                      if kind == 'Text' and len(v.strip()) >= 8
                      and v.strip() not in {'作者已关闭评论'}]
        title = max(candidates, key=len) if candidates else None
    matched, score, _ = c.video_detail_identity_match(title, author, records)
    if not title or not author or not matched:
        raise RuntimeError(f'URL target identity incomplete/mismatched ({score:.3f})')
    duration = c.resolve_video_detail_duration(surface, records, None)
    if not duration or (stored_duration and abs(duration - int(stored_duration)) > max(2, int(stored_duration) * .03)):
        raise RuntimeError('URL target duration unavailable/mismatched')
    return records, details, title, author or details.get('author_name'), duration

def try_direct_retry(c, keyword, project, fingerprint, config, db, remote, collect_comments):
    cp = c.load_video_checkpoints(db, keyword).get(fingerprint) or {}
    data = cp.get('row') or {}
    url = data.get('url')
    if not url or not c.is_valid_channels_share_url(url):
        return None
    surface = None
    try:
        surface = open_saved_video(c, url, config)
        records, details, title, author, duration = verify_target(c, surface, cp)
    except Exception as exc:
        print(json.dumps({'event':'retry_direct_url_fallback', 'keyword':keyword,
                          'fingerprint':fingerprint, 'error':str(exc)}, ensure_ascii=False), flush=True)
        if surface is not None:
            try:
                c.return_to_search_results(config)
            except Exception:
                # Do not open a new window over an unverified live detail.
                raise
        return None
    allowed = {f.name for f in fields(c.ResultRow)}
    data = {k:v for k,v in data.items() if k in allowed}
    data.update(project=project, keyword=keyword, url=url, title=title,
                author_name=author, video_duration=duration, video_count=1)
    row = c.ResultRow(**data)
    comments = cp.get('comments') or []
    try:
        def collect_fields():
            nonlocal comments
            current = c.get_video_detail_window()
            current_records, current_details, _, _, _ = verify_target(c, current, {'row':vars(row)})
            metrics = c.parse_article_metrics(current_records)
            row.like_count, row.comment_count, row.favorite_count, row.share_count = metrics
            row.published_at = current_details.get('published_at') or row.published_at
            if collect_comments:
                comments = c.collect_video_comments(current, config,
                    expected_count=row.comment_count, article_title=row.title)
            return {'verified':True}
        recording_config = dict(config, client_asr_background=True, force_asr=True,
            _capture_identity={'title':title, 'author_name':author})
        pending, _ = c.capture_client_audio_asr(title, surface, recording_config,
            duration_seconds=duration, prompt_context=None, during_capture_callback=collect_fields)
        if not isinstance(pending, c.PendingClientAsr):
            raise RuntimeError('No complete trustworthy audio; exact retry remains pending')
        c.save_row(db, row)
        if collect_comments:
            c.save_comments(db, row, comments)
        c.upsert_video_checkpoint(db, keyword=keyword, project=project,
            fingerprint=fingerprint, status='retry_pending', row=row, comments=comments,
            asr_status='pending', retry_count=int(cp.get('retry_count') or 0),
            result_index=cp.get('result_index'), remote_store=remote)
        db_path = db.execute('PRAGMA database_list').fetchone()[2]
        queue = c.BackgroundAsrQueue(c.Path(db_path), config, recovery_article_keys=set())
        queue.submit(c.article_key_for_row(row), keyword, pending,
                     fingerprint=fingerprint, project=project, remote_store=remote)
        queue.close_and_wait()
        latest = c.load_video_checkpoints(db, keyword).get(fingerprint) or {}
        complete = latest.get('status') == 'completed' and latest.get('asr_status') == 'completed'
        return {'keyword':keyword, 'saved':1 if complete else 0, 'failed':0 if complete else 1,
                'examined':1, 'status':'complete_retry_fingerprint' if complete else 'partial_retry_pending',
                'complete':complete, 'locator':'saved_url', 'retry_pending':0 if complete else 1}
    except Exception as exc:
        c.upsert_video_checkpoint(db, keyword=keyword, project=project,
            fingerprint=fingerprint, status='retry_pending', row=row,
            retry_count=int(cp.get('retry_count') or 0)+1, asr_status='retry_pending',
            last_error=str(exc), result_index=cp.get('result_index'), remote_store=remote)
        return {'keyword':keyword, 'saved':0, 'failed':1, 'examined':1,
                'status':'partial_retry_pending', 'complete':False, 'locator':'saved_url'}
    finally:
        c.return_to_search_results(config)
