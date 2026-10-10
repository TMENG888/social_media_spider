"""Fail before claiming work when the selected model cannot actually load."""
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from asr_model_loader import load_asr_model

if __name__ == '__main__':
    config = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8-sig'))
    model = load_asr_model(config)
    print(json.dumps({'event':'asr_model_preflight_passed','model':config.get('client_asr_model','small')},ensure_ascii=False),flush=True)
