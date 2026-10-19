"""Replayable search-end evidence; a non-growing result count is not EOF."""
import hashlib
import json
import math
from datetime import datetime

POLICY = '20261015-bound-search-end-v1'
TERMINAL_TEXTS = frozenset({'没有更多了', '没有更多结果', '已显示全部结果', '全部加载完毕'})


def _integer(value):
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _digest(value):
    return isinstance(value, str) and len(value) == 64 and all(c in '0123456789abcdef' for c in value)


def _time(value):
    try:
        parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return parsed.timestamp() if parsed.tzinfo is not None else None
    except (TypeError, ValueError, OverflowError):
        return None


def _context(snapshot, keyword):
    return (isinstance(snapshot, dict) and snapshot.get('keyword') == keyword
            and snapshot.get('pageTitle') == f'{keyword} - 视频 - 搜一搜'
            and snapshot.get('contextValid') is True
            and snapshot.get('loading') is False and snapshot.get('loadFailed') is False
            and _integer(snapshot.get('cardCount')) and snapshot['cardCount'] > 0
            and _digest(snapshot.get('cardDigest'))
            and _time(snapshot.get('capturedAt')) is not None)


def _position(snapshot):
    value = snapshot.get('scrollPercent')
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and 0 <= value <= 100 else None


def valid_origin(snapshot, keyword):
    if not _context(snapshot, keyword):
        return False
    return (snapshot.get('verticallyScrollable') is False
            or (_position(snapshot) is not None and _position(snapshot) <= .01))


def _bottom(snapshot):
    position = _position(snapshot)
    if snapshot.get('verticallyScrollable') is True and position is not None and position >= 99.99:
        return 'verified_scroll_bottom'
    # The UIA marker must be outside every result card, below the last card,
    # and actually visible in the exact search document, not a sidebar label.
    if (snapshot.get('terminalText') in TERMINAL_TEXTS
            and snapshot.get('terminalOutsideCards') is True
            and snapshot.get('terminalBelowCards') is True
            and snapshot.get('lastCardInViewport') is True):
        return 'verified_visible_terminal'
    return None


def assess_search_end(proof, keyword):
    if not isinstance(proof, dict) or proof.get('policy') != POLICY or proof.get('keyword') != keyword:
        return {'ok': False, 'reason': 'SEARCH_END_PROOF_MISSING'}
    origin = proof.get('origin')
    if proof.get('scanStartedAtTop') is not True or not valid_origin(origin, keyword):
        return {'ok': False, 'reason': 'SEARCH_ORIGIN_UNVERIFIED'}
    observations = proof.get('observations')
    if not isinstance(observations, list) or len(observations) != 3:
        return {'ok': False, 'reason': 'SEARCH_END_INSUFFICIENT_OBSERVATIONS'}
    observations = observations[-3:]
    signature, generations, previous_time, method = None, set(), _time(origin['capturedAt']), None
    for snapshot in observations:
        if not _context(snapshot, keyword) or not _bottom(snapshot):
            return {'ok': False, 'reason': 'SEARCH_END_SURFACE_UNVERIFIED'}
        if not _integer(snapshot.get('scannedCount')) or snapshot['scannedCount'] < snapshot['cardCount']:
            return {'ok': False, 'reason': 'SEARCH_END_UNSCANNED_CARDS'}
        current = (snapshot['cardCount'], snapshot['cardDigest'])
        if signature is not None and current != signature:
            return {'ok': False, 'reason': 'SEARCH_END_RESULT_SET_CHANGED'}
        generation = snapshot.get('surfaceGeneration')
        stamp = _time(snapshot['capturedAt'])
        if not _integer(generation) or generation in generations or (generations and generation <= max(generations)) or stamp < previous_time:
            return {'ok': False, 'reason': 'SEARCH_END_REBUILD_OR_TIME_UNVERIFIED'}
        signature, previous_time, method = current, stamp, _bottom(snapshot)
        generations.add(generation)
    return {'ok': True, 'policy': POLICY, 'scope': 'platform_current_visible_results',
            'method': method, 'verifiedCardCount': signature[0], 'observations': 3}


class SearchEndTracker:
    def __init__(self, keyword, origin, scan_started_at_top):
        self.proof = {'policy': POLICY, 'keyword': keyword, 'origin': origin,
                      'scanStartedAtTop': scan_started_at_top is True, 'observations': []}

    def observe(self, snapshot):
        self.proof['observations'] = (self.proof['observations'] + [snapshot])[-3:]
        return assess_search_end(self.proof, self.proof['keyword'])


def validate_scan_envelope(envelope, expected, *, earliest=None):
    if not isinstance(envelope, dict) or envelope.get('policy') != POLICY:
        return {'ok': False, 'reason': 'SEARCH_SCAN_ENVELOPE_MISSING'}
    for field, value in expected.items():
        if envelope.get(field) != value:
            return {'ok': False, 'reason': 'SEARCH_SCAN_IDENTITY_MISMATCH'}
    if not isinstance(envelope.get('runToken'), str) or len(envelope['runToken']) < 16:
        return {'ok': False, 'reason': 'SEARCH_SCAN_RUN_TOKEN_MISSING'}
    started, finished = _time(envelope.get('startedAt')), _time(envelope.get('finishedAt'))
    if started is None or finished is None or finished < started or (earliest is not None and started + 1 < earliest):
        return {'ok': False, 'reason': 'SEARCH_SCAN_RUN_TIME_INVALID'}
    summaries = envelope.get('summaries')
    if not isinstance(summaries, list) or len(summaries) != 1:
        return {'ok': False, 'reason': 'SEARCH_SCAN_EXACT_KEYWORD_REQUIRED'}
    summary = summaries[0]
    if not isinstance(summary, dict) or summary.get('keyword') != expected.get('keyword') or summary.get('complete') is not True:
        return {'ok': False, 'reason': 'SEARCH_SCAN_NOT_COMPLETE'}
    proof = summary.get('searchEndProof')
    result = assess_search_end(proof, expected['keyword'])
    if not result['ok']:
        return result
    times = [_time(proof['origin']['capturedAt'])] + [_time(s['capturedAt']) for s in proof['observations']]
    if min(times) < started - 1 or max(times) > finished + 1:
        return {'ok': False, 'reason': 'SEARCH_SCAN_OBSERVATIONS_OUTSIDE_RUN'}
    return {**result, 'evidenceDigest': hashlib.sha256(json.dumps(envelope, ensure_ascii=False, sort_keys=True).encode()).hexdigest()}
