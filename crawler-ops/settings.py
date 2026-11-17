"""Portable configuration for the maintained operations dashboard."""
from pathlib import Path
import json
import os
import shutil

BASE=Path(__file__).resolve().parent
CONFIG_PATH=Path(os.environ.get('CRAWLER_OPS_CONFIG',str(BASE/'config.json')))

def read_json(path,default=None):
    try:
        if path.stat().st_size>12_000_000:return default
        return json.loads(path.read_text(encoding='utf-8-sig'))
    except (OSError,ValueError):return default

config=read_json(CONFIG_PATH,None)
if config is None:config=read_json(BASE/'config.example.json',{})

def configured_path(key,default):
    p=Path(config.get(key,default))
    return p if p.is_absolute() else (CONFIG_PATH.parent/p).resolve()

PACKAGE=configured_path('package_root','..')
MONITOR=configured_path('monitor_root','../feishu-monitor')
OUTPUT=configured_path('output_dir','E:/Codex/outputs/crawler-ops')
TEMP=configured_path('temp_dir','E:/Codex/temp/crawler-ops')
HISTORY_ROOT=configured_path('history_root',str(OUTPUT/'history'))
PYTHON=Path(config.get('python') or shutil.which('python') or 'python')
NODE=Path(config.get('node') or shutil.which('node') or 'node')
SSH_CONFIG=configured_path('ssh_config','E:/Codex/config/crawler-ssh-config')
MACHINES=config.get('machines',[])
PLATFORMS={'xhs':'小红书','douyin':'抖音'}
PROJECTS=config.get('projects',['全国地产设计产品力监测'])
ACTIVE_TOPIC=config.get('active_topic','专题一')
PORT=int(config.get('port',54176))
LISTEN_HOST=config.get('listen_host','127.0.0.1')
LAN_ADDRESS=config.get('lan_address','127.0.0.1')
INTERVAL=int(config.get('interval',300))
ALLOWED_HOSTS={f'{address}:{PORT}' for address in ('127.0.0.1','localhost',LAN_ADDRESS)}

def machine(label):return next(m for m in MACHINES if m['label']==label)
def worker(m,kind):return next(p['worker'] for p in m['platformStatus'] if p['platform']==kind)
def worker_root(m,kind):return Path(m['share'])/PLATFORMS[kind]/worker(m,kind)
