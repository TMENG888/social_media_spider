"""Shared sibling-platform layout; importing monitoring never runs a collector."""
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parent
PACKAGE_ROOT=ROOT.parent
DEFAULTS={'小红书':'xiaohongshu','抖音':'douyin','视频号':'wechat-channels'}

def platform_path(platform,config=None,package=None):
    base=Path(package) if package is not None else PACKAGE_ROOT
    if config is None:
        file=ROOT/'config.json'
        config=json.loads(file.read_text(encoding='utf-8-sig')) if file.exists() else {}
    configured=config.get('platform_directories',{}).get(platform)
    directory=configured or (platform if (base/platform).is_dir() else DEFAULTS[platform])
    target=(base/directory).resolve()
    if target==base.resolve() or base.resolve() not in target.parents:
        raise ValueError('Platform directory must stay inside the package')
    return target

CHANNELS_COMMON=platform_path('视频号')/'common'
