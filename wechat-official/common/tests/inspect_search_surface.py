"""Print visible UIA controls around the 搜一搜 navigation row."""

import importlib.util
import json
import sys
from pathlib import Path


COMMON = Path(__file__).parents[1]
SOURCE = COMMON / "src" / "wechat_pc_collector.py"
SPEC = importlib.util.spec_from_file_location("wechat_pc_collector_inspect", SOURCE)
collector = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = collector
SPEC.loader.exec_module(collector)

surface = collector.get_search_window()
collector.save_window_screenshot(surface, COMMON / "tests" / "search-surface.png")
rows = []
for control in surface.descendants():
    try:
        rect = control.rectangle()
        name = (control.window_text() or "").strip()
        if control.is_visible() and (name or 60 <= rect.top <= 220):
            rows.append({
                "name": name,
                "type": control.element_info.control_type,
                "class": control.element_info.class_name,
                "automation_id": control.element_info.automation_id,
                "rect": [rect.left, rect.top, rect.right, rect.bottom],
            })
    except Exception:
        pass
print(json.dumps(rows, ensure_ascii=False, indent=2))
