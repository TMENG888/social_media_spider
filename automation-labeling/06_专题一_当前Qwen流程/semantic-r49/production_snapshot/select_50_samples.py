#!/usr/bin/env python3
"""Create a deterministic, stratified 50-article acceptance-test sample."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent
sys.path.insert(0, str(PROJECT_DIR))

import process_topic1_samples as t1

from hybrid_slice_and_label import TOPIC1, TOPIC2, choose_source, norm


PROJECT_ALIASES = {
    "北京臻澐": ["北京臻澐", "华润臻澐", "华润臻云", "臻澐", "臻云"],
    "建发海晏": ["建发海晏", "建发海宴", "海晏", "海宴"],
    "中海·安澜北京": ["中海·安澜北京", "中海安澜北京", "安澜北京", "安澜"],
}


def bucket(length: int) -> str:
    if length < 1200:
        return "短文"
    if length < 4200:
        return "中长文"
    return "长文"


def round_robin(groups: dict[str, list[dict]], count: int) -> list[dict]:
    for values in groups.values():
        values.sort(key=lambda x: (x["_length"], x["id"]))
    selected: list[dict] = []
    keys = sorted(groups)
    cursor = {key: 0 for key in keys}
    while len(selected) < count:
        progressed = False
        for key in keys:
            values = groups[key]
            index = cursor[key]
            if index < len(values):
                selected.append(values[index])
                cursor[key] += 1
                progressed = True
                if len(selected) == count:
                    break
        if not progressed:
            break
    return selected


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    with args.input.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    for row in rows:
        source, text = choose_source(row)
        row["_source"] = source
        row["_text"] = text
        row["_length"] = len(text)
        row["_bucket"] = bucket(len(text))

    topic1_groups: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        if row.get("项目") != TOPIC1 or not row["_text"]:
            continue
        haystack = " ".join([norm(row.get("关键词")), norm(row.get("文章标题")), row["_text"][:2500]])
        brand = "中海" if "中海" in haystack else "保利" if "保利" in haystack else ""
        if brand:
            topic1_groups[f"{brand}|{row['_bucket']}|{row.get('平台','')}"] .append(row)

    t1_mid = round_robin({k: v for k, v in topic1_groups.items() if k.startswith("中海|")}, 13)
    t1_poly = round_robin({k: v for k, v in topic1_groups.items() if k.startswith("保利|")}, 12)

    topic2_by_project: dict[str, dict[str, list[dict]]] = {
        name: defaultdict(list) for name in PROJECT_ALIASES
    }
    used_ids: set[str] = set()
    for row in rows:
        if row.get("项目") != TOPIC2 or not row["_text"]:
            continue
        haystack = " ".join([norm(row.get("关键词")), norm(row.get("文章标题")), row["_text"][:5000]])
        for name, aliases in PROJECT_ALIASES.items():
            if any(alias in haystack for alias in aliases):
                topic2_by_project[name][f"{row['_bucket']}|{row.get('平台','')}"] .append(row)
                break

    topic2: list[dict] = []
    targets = {"北京臻澐": 9, "建发海晏": 8, "中海·安澜北京": 8}
    for name, count in targets.items():
        picked = round_robin(topic2_by_project[name], count)
        for row in picked:
            row["_sample_project"] = name
            used_ids.add(str(row["id"]))
        topic2.extend(picked)

    selected = t1_mid + t1_poly + topic2
    if len(selected) != 50:
        raise RuntimeError(f"Expected 50 articles, selected {len(selected)}")

    overrides = {str(row["id"]): t1.infer_project(row) for row in t1_mid + t1_poly}
    config = {
        "sample_ids": [str(row["id"]) for row in selected],
        "topic1_project_overrides": overrides,
        "topic2_selected_projects": list(PROJECT_ALIASES),
        "topic2_extra_aliases": PROJECT_ALIASES,
        "sample_metadata": {
            str(row["id"]): {
                "专题": row.get("项目"),
                "平台": row.get("平台"),
                "长度分层": row["_bucket"],
                "切片来源": row["_source"],
                "来源字符数": row["_length"],
                "抽样项目": row.get("_sample_project") or overrides.get(str(row["id"]), ""),
            }
            for row in selected
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "selected": len(selected),
        "topic1": len(t1_mid) + len(t1_poly),
        "topic2": len(topic2),
        "topic1_brands": {"中海": len(t1_mid), "保利": len(t1_poly)},
        "topic2_projects": {name: targets[name] for name in targets},
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
