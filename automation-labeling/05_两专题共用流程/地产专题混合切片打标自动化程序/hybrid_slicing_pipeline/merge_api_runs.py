#!/usr/bin/env python3
"""Merge the batched 50-article run with successful repair calls."""

from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
from pathlib import Path

from hybrid_slice_and_label import validate_api_viewpoint_summary


PRICING_SOURCE = "https://www.qianwenai.com/models/qwen3.7-flash#context"
PRICING_AS_OF = "2026-09-30"
PRICING_MODE = "实时API（输入≤32K）"
INPUT_PRICE = 0.2
CACHED_INPUT_PRICE = 0.04
OUTPUT_PRICE = 0.8


def read_csv(path: Path):
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict]):
    if not rows:
        return
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def unit_article_id(row: dict) -> str:
    value = row.get("content_id") or row.get("record_id") or row.get("unit_id") or ""
    return value.split("-", 2)[1] if value.startswith(("T1-", "T2-")) else value


def integer(value) -> int:
    try:
        return int(float(value or 0))
    except (TypeError, ValueError):
        return 0


def number(value) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def cost(input_tokens: int, output_tokens: int, cached_tokens: int = 0) -> float:
    cached = min(max(cached_tokens, 0), input_tokens)
    return (
        (input_tokens - cached) / 1_000_000 * INPUT_PRICE
        + cached / 1_000_000 * CACHED_INPUT_PRICE
        + output_tokens / 1_000_000 * OUTPUT_PRICE
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-dir", required=True, type=Path)
    parser.add_argument("--repair-dir", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    repair_articles = {row["源表id"] for row in read_csv(args.repair_dir / "文章Token成本.csv")}
    args.output_dir.mkdir(parents=True, exist_ok=True)

    final_products = [x for x in read_csv(args.base_dir / "产品信息单元_API.csv") if unit_article_id(x) not in repair_articles]
    final_products += read_csv(args.repair_dir / "产品信息单元_API.csv")
    final_views = [x for x in read_csv(args.base_dir / "观点信息单元_API.csv") if unit_article_id(x) not in repair_articles]
    final_views += read_csv(args.repair_dir / "观点信息单元_API.csv")
    for row in final_views:
        summary, summary_issues = validate_api_viewpoint_summary(
            row.get("原始摘录"),
            row.get("观点摘要"),
            "",
            [
                row.get("项目名称", ""), row.get("二级标签", ""), row.get("三级标签", ""),
                row.get("四级标签", ""), row.get("五级标签", ""), row.get("标签强调方向", ""),
            ],
        )
        row["观点摘要"] = summary
        if summary_issues:
            reasons = "；".join(summary_issues)
            note = str(row.get("备注") or "")
            if "需人工复核" not in note:
                note = (note + "；需人工复核").strip("；")
            row["备注"] = (note + "；" + reasons).strip("；")

    calls = []
    for phase, directory in [("首轮分批", args.base_dir), ("失败项细分重跑", args.repair_dir)]:
        for row in read_csv(directory / "API调用明细.csv"):
            input_value = integer(row.get("输入Token"))
            cached_value = integer(row.get("缓存命中Token"))
            output_value = integer(row.get("输出Token"))
            calculated_cost = cost(input_value, output_value, cached_value)
            row.update({
                "缓存命中Token": cached_value,
                "计价模式": PRICING_MODE,
                "输入单价": INPUT_PRICE,
                "缓存输入单价": CACHED_INPUT_PRICE,
                "输出单价": OUTPUT_PRICE,
                "按配置单价计算费用": round(calculated_cost, 8),
                "计费费用": round(calculated_cost, 8),
                "价格来源": PRICING_SOURCE,
                "价格日期": PRICING_AS_OF,
            })
            calls.append({"阶段": phase, **row})

    base_articles = {x["源表id"]: x for x in read_csv(args.base_dir / "文章Token成本.csv")}
    repaired = {x["源表id"]: x for x in read_csv(args.repair_dir / "文章Token成本.csv")}
    final_articles = []
    for article_id, row in base_articles.items():
        final = dict(row)
        production = repaired.get(article_id) if article_id in repaired else row
        if article_id in repaired:
            fix = repaired[article_id]
            final["API输出单元数"] = fix["API输出单元数"]
            final["API调用次数"] = integer(row["API调用次数"]) + integer(fix["API调用次数"])
            for field in ["输入Token", "输出Token", "总Token"]:
                final[field] = integer(row[field]) + integer(fix[field])
            final["响应秒数"] = round(number(row["响应秒数"]) + number(fix["响应秒数"]), 3)
            final["请求状态"] = "success_after_repair"
            final["错误"] = ("首轮：" + row.get("错误", "") + "；修复：" + fix.get("错误", "")).strip("；")
            final["校验问题"] = fix.get("校验问题", "")
        gross_input = integer(final.get("输入Token"))
        gross_cached = integer(final.get("缓存命中Token"))
        gross_output = integer(final.get("输出Token"))
        production_input = integer(production.get("输入Token"))
        production_cached = integer(production.get("缓存命中Token"))
        production_output = integer(production.get("输出Token"))
        production_cost = cost(production_input, production_output, production_cached)
        gross_cost = cost(gross_input, gross_output, gross_cached)
        final.update({
            "缓存命中Token": gross_cached,
            "生产输入Token": production_input,
            "生产缓存命中Token": production_cached,
            "生产输出Token": production_output,
            "生产总Token": production_input + production_output,
            "费用": round(production_cost, 8),
            "生产费用": round(production_cost, 8),
            "验收实际费用": round(gross_cost, 8),
            "重试开销费用": round(gross_cost - production_cost, 8),
            "计价模式": PRICING_MODE,
            "输入单价": INPUT_PRICE,
            "缓存输入单价": CACHED_INPUT_PRICE,
            "输出单价": OUTPUT_PRICE,
            "价格来源": PRICING_SOURCE,
            "价格日期": PRICING_AS_OF,
        })
        final_articles.append(final)

    review_rows = []
    for kind, rows in [("产品信息单元", final_products), ("观点信息单元", final_views)]:
        for row in rows:
            if "需人工复核" in str(row.get("备注", "")):
                review_rows.append({
                    "单元类型": kind,
                    "源表id": unit_article_id(row),
                    "unit_id": row.get("unit_id"),
                    "项目": row.get("项目") or row.get("项目名称"),
                    "标签路径ID": row.get("标签路径ID"),
                    "一级标签": row.get("一级标签"),
                    "二级标签": row.get("二级标签"),
                    "三级标签": row.get("三级标签"),
                    "四级标签": row.get("四级标签"),
                    "五级标签": row.get("五级标签"),
                    "原始证据": row.get("原文摘录") or row.get("原始摘录"),
                    "复核原因": row.get("备注"),
                })

    totals = [integer(x["总Token"]) for x in final_articles]
    input_tokens = [integer(x["输入Token"]) for x in final_articles]
    output_tokens = [integer(x["输出Token"]) for x in final_articles]
    latencies = [number(x["响应秒数"]) for x in final_articles]
    ordered = sorted(totals)
    p90 = ordered[max(0, math.ceil(len(ordered) * 0.9) - 1)]
    base_cost_rows = read_csv(args.base_dir / "文章Token成本.csv")
    repair_cost_rows = read_csv(args.repair_dir / "文章Token成本.csv")
    production_rows = [x for x in base_cost_rows if x["请求状态"] == "success"] + repair_cost_rows
    production_input = sum(integer(x["输入Token"]) for x in production_rows)
    production_output = sum(integer(x["输出Token"]) for x in production_rows)
    production_total = sum(integer(x["总Token"]) for x in production_rows)
    production_cached = sum(integer(x.get("缓存命中Token")) for x in production_rows)
    production_calls = sum(integer(x["API调用次数"]) for x in production_rows)
    production_latencies = [number(x["响应秒数"]) for x in production_rows]
    production_article_totals = [integer(x["总Token"]) for x in production_rows]
    production_ordered = sorted(production_article_totals)
    production_cost = cost(production_input, production_output, production_cached)
    gross_cached = sum(integer(x.get("缓存命中Token")) for x in final_articles)
    gross_cost = cost(sum(input_tokens), sum(output_tokens), gross_cached)
    output_units = len(final_products) + len(final_views)
    summary = {
        "articles": len(final_articles),
        "successful_articles": sum(x["请求状态"].startswith("success") for x in final_articles),
        "api_calls": len(calls),
        "product_units": len(final_products),
        "viewpoint_units": len(final_views),
        "review_units": len(review_rows),
        "input_tokens": sum(input_tokens),
        "output_tokens": sum(output_tokens),
        "total_tokens": sum(totals),
        "average_input_tokens_per_article": round(statistics.mean(input_tokens), 2),
        "average_output_tokens_per_article": round(statistics.mean(output_tokens), 2),
        "average_total_tokens_per_article": round(statistics.mean(totals), 2),
        "median_total_tokens_per_article": round(statistics.median(totals), 2),
        "p90_total_tokens_per_article": p90,
        "average_latency_seconds_per_article": round(statistics.mean(latencies), 3),
        "production_api_calls": production_calls,
        "production_input_tokens": production_input,
        "production_output_tokens": production_output,
        "production_cached_input_tokens": production_cached,
        "production_total_tokens": production_total,
        "production_average_tokens_per_article": round(statistics.mean(production_article_totals), 2),
        "production_median_tokens_per_article": round(statistics.median(production_article_totals), 2),
        "production_p90_tokens_per_article": production_ordered[max(0, math.ceil(len(production_ordered) * 0.9) - 1)],
        "production_average_latency_seconds_per_article": round(statistics.mean(production_latencies), 3),
        "production_average_tokens_per_output_unit": round(production_total / max(1, len(final_products) + len(final_views)), 2),
        "retry_overhead_tokens": sum(totals) - production_total,
        "production_input_cost": round((production_input - production_cached) / 1_000_000 * INPUT_PRICE + production_cached / 1_000_000 * CACHED_INPUT_PRICE, 8),
        "production_output_cost": round(production_output / 1_000_000 * OUTPUT_PRICE, 8),
        "production_total_cost": round(production_cost, 8),
        "production_average_cost_per_article": round(production_cost / max(1, len(final_articles)), 9),
        "production_average_cost_per_output_unit": round(production_cost / max(1, output_units), 10),
        "gross_acceptance_cost": round(gross_cost, 8),
        "retry_overhead_cost": round(gross_cost - production_cost, 8),
        "total_cost": round(production_cost, 8),
        "average_cost_per_article": round(production_cost / max(1, len(final_articles)), 9),
        "pricing_mode": PRICING_MODE,
        "input_price_per_million": INPUT_PRICE,
        "cached_input_price_per_million": CACHED_INPUT_PRICE,
        "output_price_per_million": OUTPUT_PRICE,
        "pricing_source": PRICING_SOURCE,
        "pricing_as_of": PRICING_AS_OF,
        "pricing_note": "按用户提供的Qwen3.7-Flash实时API价格计算；本次实测缓存命中Token为0。价格可能调整，正式结算以平台账单为准。",
        "cost_formula": "(输入Token-缓存命中Token)/1000000×输入单价+缓存命中Token/1000000×缓存输入单价+输出Token/1000000×输出单价",
    }
    write_csv(args.output_dir / "产品信息单元_API.csv", final_products)
    write_csv(args.output_dir / "观点信息单元_API.csv", final_views)
    write_csv(args.output_dir / "文章Token成本.csv", final_articles)
    write_csv(args.output_dir / "API调用明细.csv", calls)
    write_csv(args.output_dir / "复核队列.csv", review_rows)
    (args.output_dir / "api_test_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
