"""Webhook transport: retry only faults known to precede any HTTP request.

Timeouts, resets, invalid responses and HTTP/server errors have ambiguous POST
outcomes. Never retry those automatically or expose a credential-bearing URL.
"""
import base64
import hashlib
import hmac
import json
import socket
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse


class DeliveryError(RuntimeError):
    def __init__(self, code, *, outcome='unknown', retry_safe=False, attempts=1, service_code=None):
        super().__init__(code)
        self.code, self.outcome = code, outcome
        self.retry_safe, self.attempts, self.service_code = retry_safe, attempts, service_code

    def record(self):
        value = {'errorCode': self.code, 'deliveryOutcome': self.outcome,
                 'retrySafe': self.retry_safe, 'attempts': self.attempts}
        if isinstance(self.service_code, int):
            value['serviceCode'] = self.service_code
        return value


def send(payload, webhook, secret='', *, opener=None, sleep=None, on_retry=None):
    opener, sleep = opener or urllib.request.urlopen, sleep or time.sleep
    url = urlparse(webhook)
    if (url.scheme != 'https' or url.hostname != 'open.feishu.cn'
            or not url.path.startswith('/open-apis/bot/v2/hook/') or url.username or url.password):
        raise DeliveryError('FEISHU_WEBHOOK_INVALID', outcome='not_attempted')
    for attempt in range(1, 4):
        body = dict(payload)
        if secret:
            stamp = str(int(time.time()))
            body.update(timestamp=stamp, sign=base64.b64encode(hmac.new(
                (stamp + '\n' + secret).encode(), b'', hashlib.sha256).digest()).decode())
        request = urllib.request.Request(webhook, json.dumps(body, ensure_ascii=False).encode(),
                                         {'Content-Type': 'application/json'}, method='POST')
        try:
            with opener(request, timeout=15) as response:
                result = json.load(response)
        except urllib.error.HTTPError as exc:
            raise DeliveryError('FEISHU_HTTP_ERROR', attempts=attempt, service_code=exc.code) from None
        except Exception as exc:
            reason = exc.reason if isinstance(exc, urllib.error.URLError) else exc
            # DNS and explicit connect-refused/unreachable are before request
            # transmission. A timeout/reset can also occur after acceptance.
            safe = (isinstance(reason, (socket.gaierror, ConnectionRefusedError))
                    or isinstance(reason, OSError) and reason.errno in (101, 111, 113, 10051, 10061, 10065))
            code = ('FEISHU_DNS_FAILED' if isinstance(reason, socket.gaierror) else
                    'FEISHU_CONNECT_FAILED' if safe else 'FEISHU_DELIVERY_UNKNOWN')
            if safe and attempt < 3:
                wait = (3, 8)[attempt - 1]
                if on_retry:
                    on_retry({'event': 'feishu_connect_retry', 'errorCode': code,
                              'attempt': attempt, 'nextAttempt': attempt + 1, 'waitSeconds': wait,
                              'deliveryOutcome': 'not_sent', 'retrySafe': True})
                sleep(wait)
                continue
            raise DeliveryError(code, outcome='not_sent' if safe else 'unknown',
                                retry_safe=safe, attempts=attempt) from None
        if not isinstance(result, dict):
            raise DeliveryError('FEISHU_INVALID_RESPONSE', attempts=attempt)
        code = result.get('code', result.get('StatusCode'))
        if isinstance(code, bool) or not isinstance(code, int):
            raise DeliveryError('FEISHU_INVALID_RESPONSE', attempts=attempt)
        if code != 0:
            raise DeliveryError('FEISHU_REJECTED', outcome='rejected', attempts=attempt, service_code=code)
        return True
