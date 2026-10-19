"""Conservative artifact screen; passing is not proof of spoken accuracy."""
import json
import re
from pathlib import Path

_RULES = json.loads(Path(__file__).with_name('transcript-quality-rules.json').read_text(encoding='utf-8'))
POLICY = _RULES['policy']


def transcript_artifact(value):
    # The JS readback and live decoder inspect the same RAW text. Cleaning an
    # outro away must not turn a suspect decoding into an accepted subtitle.
    normalized = re.sub(r'[^0-9A-Za-z\u4e00-\u9fff]', '', str(value or '')).lower()
    return next((marker for marker in _RULES['contains'] if marker in normalized), None)
