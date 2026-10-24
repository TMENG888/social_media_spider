"""Bounded checkpoint transport retries. No task claims, ACKs or resets."""
import json
import time


def retry_checkpoint(operation, *, delays=(1, 2), pause=None, log=None):
    pause = pause or time.sleep
    log = log or (lambda event: print(json.dumps(event), flush=True))
    for attempt in range(1, len(delays) + 2):
        try:
            result = operation()
            if attempt > 1:
                log({'event': 'redis_checkpoint_retry_recovered', 'attempt': attempt})
            return result
        except OSError as error:
            # Includes timeout, DNS and unreachable-host errors. Never use the
            # exception text: socket messages may contain connection details.
            if attempt > len(delays):
                log({'event': 'redis_checkpoint_circuit_open', 'attempt': attempt,
                     'errorType': type(error).__name__, 'localCheckpointRetained': True,
                     'remoteSyncConfirmed': False, 'taskConfirmed': False})
                raise
            log({'event': 'redis_checkpoint_retry_wait', 'attempt': attempt,
                 'nextAttempt': attempt + 1, 'seconds': delays[attempt-1],
                 'errorType': type(error).__name__})
            pause(delays[attempt-1])
