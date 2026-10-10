from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
TASK_DIR = ROOT / "common" / "tasks"
WORKER_COUNT = 3


def load_topic(name: str) -> list[dict]:
    path = TASK_DIR / f"{name}_keywords.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload["keywords"]
    for row in rows:
        row["executionMode"] = "wechat_channels_pc"
    path.write_text(json.dumps({"keywords": rows}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return rows


def task(topic: str, keywords: list[str]) -> dict:
    return {
        "id": topic,
        "name": "专题一" if topic == "topic1" else "专题二",
        "keywordsFile": f"common/tasks/{topic}_keywords.json",
        "collectComments": topic == "topic2",
        "transitionDelaySeconds": 10,
        "keywordAllowList": keywords,
    }


def main() -> None:
    topics = {name: load_topic(name) for name in ("topic1", "topic2")}
    assignments = {
        worker: {
            topic: [row["keyword"] for index, row in enumerate(rows) if index % WORKER_COUNT == worker]
            for topic, rows in topics.items()
        }
        for worker in range(WORKER_COUNT)
    }
    queue_base = {"version": 1, "cutoff": "2026-01-01", "maxResultsPerKeyword": 0}
    common_queue = {
        **queue_base,
        "tasks": [task("topic1", [row["keyword"] for row in topics["topic1"]]), task("topic2", [row["keyword"] for row in topics["topic2"]])],
    }
    (ROOT / "common" / "task-queue.json").write_text(json.dumps(common_queue, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary = {"workerCount": WORKER_COUNT, "totalChannelsKeywords": sum(map(len, topics.values())), "byWorker": []}
    for worker_index in range(WORKER_COUNT):
        worker_name = f"worker-{worker_index + 1:02d}"
        worker_root = ROOT / worker_name
        worker_root.mkdir(parents=True, exist_ok=True)
        topic1 = assignments[worker_index]["topic1"]
        topic2 = assignments[worker_index]["topic2"]
        queue = {**queue_base, "tasks": [task("topic1", topic1), task("topic2", topic2)]}
        (worker_root / "task-queue.json").write_text(json.dumps(queue, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        summary["byWorker"].append({"worker": worker_name, "topic1": len(topic1), "topic2": len(topic2), "total": len(topic1) + len(topic2)})
    summary["duplicateAssignments"] = []
    summary["unassigned"] = []
    (TASK_DIR / "worker_shards.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
