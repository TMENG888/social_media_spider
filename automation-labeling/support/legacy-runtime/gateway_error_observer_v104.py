"""Sanitized error-only diagnostic hook; never changes HTTP/auth decisions."""
import re
import time


def safe_error(value, secret):
    text = str(value).replace(secret, '[REDACTED]') if secret else str(value)
    return re.sub(r'(?i)(bearer\s+|sk-)[A-Za-z0-9_.\-]+', '[REDACTED]', text)[:1500]


def observe(transport, save):
    def wrapped(url, body, key, timeout=120):
        response = transport(url, body, key, timeout=timeout)
        if response.status_code >= 400:
            entry = {'http_status': response.status_code, 'captured_at': time.time(),
                     'credentials_and_request_body_not_saved': True}
            try:
                raw = response.json()
                detail = raw.get('error', raw) if isinstance(raw, dict) else {}
                if isinstance(detail, dict):
                    entry['gateway_error'] = {name: safe_error(detail[name], key)
                        for name in ('message', 'type', 'code', 'param') if name in detail}
                else:
                    entry['gateway_error'] = {'message': safe_error(detail, key)}
            except (ValueError, TypeError, KeyError):
                entry['body_not_json'] = True
            save(entry)
        return response
    return wrapped
