"""Keyword acceptance is distinct from finite child-retry disposition."""
import hashlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from urllib.parse import urlsplit

POLICY = '20261015-usable-db-80-v1'


def _identity_parts(checkpoint):
    project = str(checkpoint.get('project') or '').strip()
    article_key = str(checkpoint.get('article_key') or '').strip()
    row = checkpoint.get('row') or {}
    canonical_url = ''
    try:
        parsed = urlsplit(str(row.get('url') or '').strip())
        if (parsed.scheme.lower() == 'https' and parsed.netloc.lower() == 'weixin.qq.com'
                and re.fullmatch(r'/sph/[0-9A-Za-z_-]{8,}/?', parsed.path)):
            canonical_url = 'https://weixin.qq.com' + parsed.path.rstrip('/')
    except ValueError:
        pass
    return project, article_key, canonical_url


def _result_groups(checkpoints):
    # A card fingerprint is a discovery observation, not a unique video: titles
    # can truncate/change between scans. Deduplicate only explicit video/DB
    # identity, never title similarity or unknown/malformed links.
    parts = {fp: _identity_parts(cp) for fp, cp in checkpoints.items()}
    urls_by_key = {}
    for project, key, url in parts.values():
        if project and key and url:
            urls_by_key.setdefault((project, key), set()).add(url)
    groups = {}
    for fp, (project, key, url) in parts.items():
        known_urls = urls_by_key.get((project, key), set())
        if project and not url and key and len(known_urls) == 1:
            url = next(iter(known_urls))
        if project and url:
            identity = ('url', project, url)
        elif project and key and not known_urls:
            identity = ('article', project, key)
        else:
            # Conflicting share URLs must not make an unknown alias disappear.
            identity = ('checkpoint', fp)
        groups.setdefault(identity, []).append(fp)
    return groups


def assess_coverage(checkpoints, verified, *, scan_complete=False):
    eligible = dict(checkpoints)
    groups = _result_groups(eligible)
    verified_set = set(verified)
    usable = [fp for fp, cp in eligible.items()
              if fp in verified_set and cp.get('status') in {'completed', 'no_content', 'not_applicable'}]
    usable_set = set(usable)
    usable_results = [identity for identity, fps in groups.items() if any(fp in usable_set for fp in fps)]
    numerator, denominator = len(usable_results), len(groups)
    return {'policy': POLICY, 'ok': bool(scan_complete and (not denominator or numerator*5 >= denominator*4)),
            'scanComplete': bool(scan_complete), 'dbReadbackVerified': True,
            'numerator': numerator, 'denominator': denominator,
            'unresolved': denominator-numerator, 'ratio': numerator/denominator if denominator else None,
            'emptyScope': not denominator,
            'discoveredCheckpointCount': len(eligible),
            'duplicateCheckpointCount': len(eligible)-denominator,
            'discoveredDigest': hashlib.sha256(json.dumps(sorted(eligible)).encode()).hexdigest(),
            'usableDigest': hashlib.sha256(json.dumps(sorted(usable)).encode()).hexdigest(),
            'uniqueResultDigest': hashlib.sha256(json.dumps(sorted(groups)).encode()).hexdigest(),
            'usableResultDigest': hashlib.sha256(json.dumps(sorted(usable_results)).encode()).hexdigest()}

def verify_database_coverage(checkpoints, *, scan_complete=False, collect_comments=True):
    source = Path(__file__).resolve().parent
    bundled = source.parent/'runtime'/'node'/'node.exe'
    node = str(bundled) if bundled.is_file() else shutil.which('node')
    if not node:
        return {'ok': False, 'reason': 'DB_READBACK_RUNTIME_MISSING', 'policy': POLICY}
    # Credentials stay in the existing process environment, never argv/files.
    try:
        process = subprocess.run([node, str(source/'verify-keyword-coverage.mjs')],
            input=json.dumps({'checkpoints': checkpoints, 'scanComplete': scan_complete,
                              'collectComments': collect_comments is not False}),
            capture_output=True, text=True, encoding='utf-8', timeout=180,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0), env=os.environ.copy())
        if process.returncode:
            return {'ok': False, 'reason': 'DB_READBACK_FAILED', 'policy': POLICY}
        result = json.loads(process.stdout)
        if not isinstance(result.get('verifiedFingerprints'), list):
            raise ValueError('Missing verified identities')
        return assess_coverage(checkpoints, result['verifiedFingerprints'], scan_complete=scan_complete)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return {'ok': False, 'reason': 'DB_READBACK_FAILED', 'policy': POLICY}
