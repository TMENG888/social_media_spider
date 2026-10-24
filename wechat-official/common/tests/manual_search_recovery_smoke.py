"""Manual real-WeChat smoke test; it does not open articles or write data."""

import importlib.util
import json
import sys
import time
from pathlib import Path

from pywinauto import keyboard


COMMON = Path(__file__).parents[1]
SOURCE = COMMON / "src" / "wechat_pc_collector.py"
SPEC = importlib.util.spec_from_file_location("wechat_pc_collector_smoke", SOURCE)
collector = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = collector
SPEC.loader.exec_module(collector)

config = collector.load_config(COMMON / "collector_config.json")
keyword = sys.argv[1] if len(sys.argv) > 1 else "中海 玖序"
collector.search_in_web(keyword, config)
surface = collector.get_search_window()
before = collector.SEARCH_LAYOUT

if before == "detached":
    surface.set_focus()
    keyboard.send_keys("%{F4}", pause=0.05)
    time.sleep(1.0)
else:
    # Leave the embedded search page without terminating the main client.
    collector.click_named_surface_control(collector.get_wechat_window(), "聊天")
    time.sleep(1.0)

collector.search_in_web(keyword, config)
recovered = collector.get_search_window()
ok = collector.is_article_results_page(recovered)
print(json.dumps({
    "ok": ok,
    "keyword": keyword,
    "layout_before": before,
    "layout_after": collector.SEARCH_LAYOUT,
    "article_page": ok,
}, ensure_ascii=False))
raise SystemExit(0 if ok else 2)
