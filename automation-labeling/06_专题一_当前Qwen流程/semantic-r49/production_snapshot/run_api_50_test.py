#!/usr/bin/env python3
"""Use qwen3.7-flash to audit/merge/split the 50-article rule candidates."""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import defaultdict
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent
sys.path.insert(0, str(PROJECT_DIR))

from hybrid_slice_and_label import (
    PRODUCT_FIELDS,
    TOPIC1,
    TOPIC2,
    VIEWPOINT_FIELDS,
    choose_source,
    validate_api_viewpoint_summary,
    write_csv,
)
from llm_api_client import LlmApiClient


PRICING_SOURCE = "https://www.qianwenai.com/models/qwen3.7-flash#context"
PRICING_AS_OF = "2026-09-30"
PRICING_MODES = {
    "realtime": {
        "label": "实时API（输入≤32K）",
        "input": 0.2,
        "cached_input": 0.04,
        "output": 0.8,
    },
    "batch_file": {
        "label": "Batch File",
        "input": 0.1,
        "cached_input": 0.1,
        "output": 0.4,
    },
    "batch_chat": {
        "label": "Batch Chat（限时价格）",
        "input": 0.1,
        "cached_input": 0.1,
        "output": 0.4,
    },
}


def calculate_cost(
    prompt_tokens: int | None,
    cached_tokens: int | None,
    completion_tokens: int | None,
    input_price: float,
    cached_input_price: float,
    output_price: float,
) -> float | None:
    if prompt_tokens is None or completion_tokens is None:
        return None
    cached = min(max(int(cached_tokens or 0), 0), int(prompt_tokens))
    uncached = int(prompt_tokens) - cached
    return (
        uncached / 1_000_000 * input_price
        + cached / 1_000_000 * cached_input_price
        + int(completion_tokens) / 1_000_000 * output_price
    )


SYSTEM_PROMPT = """你是房地产社媒数据的切片与标注校验器。输入已经过规则预切分。
你的任务是基于原始证据合并重复候选、拆开混合观点，并从候选中选择唯一的最新VOC五级标签路径。
必须遵守：
1. 只能返回候选中已有的tag_id与项目，禁止创造、拼接或改写任何一级至五级标签。
2. 证据必须来自候选原文摘录，禁止补写事实、数字、品牌、项目或情绪。
3. 相同tag_id且同一项目的重复证据可合并；不同tag_id、不同项目或不同情绪对象不得合并。
4. 价格/面积/开盘等事实本身是中性，只有原文明示态度时才能标正向或负向。
5. confidence范围0到1；项目不明、多项目比较、反问、标签冲突或证据不足时给出review_reason。
6. 对专题二，practice_or_summary必须是独立、完整的观点摘要，包含项目或评价对象以及核心事实或态度；不得新增证据中没有的事实、数字、品牌、项目或情绪。
7. 专题二摘要通常控制在20至80个汉字。多句话只保留共同核心观点，去掉宣传修饰、重复表述、平台套话和无关背景。
8. 原始证据超过40字时，禁止把原文原样复制为摘要；证据很短且本身已经完整时允许摘要与原文相同。
9. 无法安全生成摘要时，practice_or_summary返回空字符串，并在review_reason中写“摘要待复核”，不得静默复制原文。
10. 返回格式：{"article_id":"...","units":[{"source_unit_ids":["..."],"project":"...","tag_id":"VOC-0001","practice_or_summary":"...","sentiment":"正向|负向|中性|无态度","expression_type":"事实介绍|正向评价|中性评价|负向评价|需求提问|对比判断|未来推测","innovation_type":"...","innovation_level":"...","confidence":0.0,"review_reason":"..."}]}。
没有有效单元时返回空units。不要返回Markdown。"""


def load_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def article_id_from_unit(unit: dict[str, Any]) -> str:
    value = unit.get("content_id") or unit.get("record_id") or ""
    return value.split("-", 1)[-1]


def compact_candidate(unit: dict[str, Any], topic: str) -> dict[str, Any]:
    label = {
        "tag_id": unit.get("标签路径ID"), "source_number": unit.get("标签编号"),
        "l1": unit.get("一级标签"), "l2": unit.get("二级标签"), "l3": unit.get("三级标签"),
        "l4": unit.get("四级标签"), "l5": unit.get("五级标签"),
        "emphasis": unit.get("标签强调方向"), "instruction": unit.get("打标说明"),
    }
    if topic == TOPIC1:
        return {
            "unit_id": unit.get("unit_id"), "project": unit.get("项目"),
            "evidence": unit.get("原文摘录"), **label,
            "practice": unit.get("具体产品做法"), "innovation_type": unit.get("创新类型"),
            "innovation_level": unit.get("创新等级"), "rule_note": unit.get("备注"),
        }
    return {
        "unit_id": unit.get("unit_id"), "project": unit.get("项目名称"),
        "evidence": unit.get("原始摘录"), **label,
        "summary": unit.get("观点摘要"), "sentiment": unit.get("情绪态度"),
        "expression_type": unit.get("表达类型"), "rule_note": unit.get("备注"),
    }


def validate_and_materialize(
    article_id: str, topic: str, candidates: list[dict[str, Any]], result: dict[str, Any] | None
) -> tuple[list[dict[str, Any]], list[str]]:
    by_id = {item["unit_id"]: item for item in candidates}
    issues: list[str] = []
    if not result or not isinstance(result.get("units"), list):
        return [], ["模型未返回有效units数组"]
    output: list[dict[str, Any]] = []
    for index, item in enumerate(result["units"], 1):
        source_ids = [str(x) for x in item.get("source_unit_ids", []) if str(x) in by_id]
        if not source_ids:
            issues.append(f"返回单元{index}无有效source_unit_ids")
            continue
        bases = [by_id[x] for x in source_ids]
        allowed_projects = {x.get("项目") if topic == TOPIC1 else x.get("项目名称") for x in bases}
        allowed_tags = {str(x.get("标签路径ID")): x for x in bases if x.get("标签路径ID")}
        project = item.get("project")
        tag_id = str(item.get("tag_id") or "")
        confidence = float(item.get("confidence") or 0)
        review_reason = str(item.get("review_reason") or "").strip()
        if project not in allowed_projects:
            project = sorted(str(x) for x in allowed_projects if x)[0] if any(allowed_projects) else '待判断'
            review_reason = (review_reason + "；项目超出候选范围，已回退").strip("；")
            confidence = min(confidence, 0.6)
        if tag_id not in allowed_tags:
            tag_id = str(bases[0].get("标签路径ID") or "")
            review_reason = (review_reason + "；标签路径ID超出候选范围，已回退").strip("；")
            confidence = min(confidence, 0.6)
        matching_bases = [x for x in bases if str(x.get("标签路径ID")) == tag_id]
        base = dict(matching_bases[0] if matching_bases else bases[0])
        evidence_field = "原文摘录" if topic == TOPIC1 else "原始摘录"
        evidence = "；".join(dict.fromkeys(str(x.get(evidence_field) or "") for x in (matching_bases or bases)))[:1000]
        base["unit_id"] = f"{'T1' if topic == TOPIC1 else 'T2'}-{article_id}-L{index:03d}"
        base[evidence_field] = evidence
        if topic == TOPIC1:
            base["项目"] = project
            base["具体产品做法"] = str(item.get("practice_or_summary") or base.get("具体产品做法") or "")[:420]
            base["创新类型"] = item.get("innovation_type") or base.get("创新类型")
            base["创新等级"] = item.get("innovation_level") or base.get("创新等级")
        else:
            base["项目名称"] = project
            object_terms = [
                str(project or ""), str(base.get("二级标签") or ""), str(base.get("三级标签") or ""),
                str(base.get("四级标签") or ""), str(base.get("五级标签") or ""),
                str(base.get("标签强调方向") or ""),
            ]
            viewpoint_summary, summary_issues = validate_api_viewpoint_summary(
                evidence,
                item.get("practice_or_summary"),
                base.get("观点摘要"),
                object_terms,
            )
            base["观点摘要"] = viewpoint_summary
            if summary_issues:
                review_reason = "；".join(dict.fromkeys(
                    [x for x in [review_reason, *summary_issues] if x]
                ))
                confidence = min(confidence, 0.84)
            base["情绪态度"] = item.get("sentiment") if item.get("sentiment") in {"正向", "负向", "中性", "无态度"} else base.get("情绪态度")
            base["表达类型"] = item.get("expression_type") or base.get("表达类型")
            base["明确评价标记"] = int(base["表达类型"] in {"正向评价", "中性评价", "负向评价", "对比判断"})
            base["正负评价标记"] = int(base["情绪态度"] in {"正向", "负向"})
            base["需求提问标记"] = int(base["表达类型"] == "需求提问")
        decision = "需人工复核" if review_reason or confidence < 0.85 else "自动通过"
        base["备注"] = f"API混合处理；{decision}；置信度={confidence:.2f}" + (f"；{review_reason}" if review_reason else "")
        output.append(base)
    return output, issues


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--rule-json", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--api-base-url", default="http://127.0.0.1:3000")
    parser.add_argument("--model", default="qwen3.7-flash")
    parser.add_argument("--candidate-batch-size", type=int, default=6)
    parser.add_argument("--concurrency", type=int, default=4, help="Maximum concurrent articles/API calls (1-16)")
    parser.add_argument("--only-ids", default="", help="Comma-separated subset used to repair failed articles")
    parser.add_argument("--pricing-mode", choices=sorted(PRICING_MODES), default="realtime")
    parser.add_argument("--input-price-per-million", type=float)
    parser.add_argument("--cached-input-price-per-million", type=float)
    parser.add_argument("--output-price-per-million", type=float)
    args = parser.parse_args()
    if not 1 <= args.concurrency <= 16:
        parser.error("--concurrency must be between 1 and 16")
    if args.candidate_batch_size < 1:
        parser.error("--candidate-batch-size must be positive")

    pricing = PRICING_MODES[args.pricing_mode]
    input_price = pricing["input"] if args.input_price_per_million is None else args.input_price_per_million
    cached_input_price = pricing["cached_input"] if args.cached_input_price_per_million is None else args.cached_input_price_per_million
    output_price = pricing["output"] if args.output_price_per_million is None else args.output_price_per_million

    config = json.loads(args.config.read_text(encoding="utf-8"))
    sample_ids = list(map(str, config["sample_ids"]))
    if args.only_ids:
        only = set(x.strip() for x in args.only_ids.split(",") if x.strip())
        sample_ids = [x for x in sample_ids if x in only]
    wanted = set(sample_ids)
    source_rows = {str(x["id"]): x for x in load_csv(args.input) if str(x.get("id")) in wanted}
    rule_payload = json.loads(args.rule_json.read_text(encoding="utf-8"))
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for unit in rule_payload["product_units"] + rule_payload["viewpoint_units"]:
        grouped[article_id_from_unit(unit)].append(unit)

    missing = wanted - set(source_rows)
    if missing:
        raise ValueError(f"Sample IDs missing from input: {sorted(missing)[:10]}")
    if len(sample_ids) != len(wanted):
        raise ValueError("Duplicate sample IDs are not allowed")
    # Validate credentials before scheduling work; no secret is printed.
    probe = LlmApiClient(args.api_base_url, args.model)
    probe.session.close()
    started = time.perf_counter()
    calls, article_costs, products, viewpoints, reviews = [], [], [], [], []
    def process_article(sequence: int, article_id: str):
        # Independent Session per worker/article. Batches stay sequential within
        # each article, so HTTP concurrency never exceeds --concurrency.
        client = LlmApiClient(args.api_base_url, args.model)
        local_calls = []
        article_started = time.perf_counter()
        row = source_rows[article_id]
        topic = row.get("项目")
        candidates = grouped.get(article_id, [])
        source_type, text = choose_source(row)
        batches = [candidates[i:i + args.candidate_batch_size] for i in range(0, len(candidates), args.candidate_batch_size)] or [[]]
        result_units, article_metrics, article_batch_issues = [], [], []
        for batch_number, batch in enumerate(batches, 1):
            compact = [compact_candidate(x, topic) for x in batch]
            prompt = json.dumps({
                "article_id": article_id, "topic": topic, "title": row.get("文章标题"),
                "keyword": row.get("关键词"), "platform": row.get("平台"),
                "text_source": source_type, "source_characters": len(text),
                "batch_number": batch_number, "batch_count": len(batches),
                "candidate_units": compact,
            }, ensure_ascii=False, separators=(",", ":"))
            result, metrics = client.chat_json(SYSTEM_PROMPT, prompt)
            valid_units = result.get("units") if result and isinstance(result.get("units"), list) else None
            if metrics.get("status") == "success" and valid_units is not None:
                result_units.extend(result["units"])
                if not valid_units:
                    article_batch_issues.append(f"第{batch_number}批模型返回合法空单元，未复活本地候选")
            elif batch:
                fallback_reason = "API调用失败" if metrics.get("status") != "success" else "API未返回有效候选单元"
                article_batch_issues.append(f"第{batch_number}批{fallback_reason}，已保留本地预标并进入复核")
                for candidate in batch:
                    result_units.append({
                        "source_unit_ids": [candidate.get("unit_id")],
                        "project": candidate.get("项目") if topic == TOPIC1 else candidate.get("项目名称"),
                        "tag_id": candidate.get("标签路径ID"),
                        "practice_or_summary": "",
                        "confidence": 0.0,
                        "review_reason": fallback_reason + ("；摘要待复核" if topic == TOPIC2 else ""),
                    })
            prompt_tokens = metrics.get("prompt_tokens")
            cached_tokens = metrics.get("cached_input_tokens") or 0
            completion_tokens = metrics.get("completion_tokens")
            calculated_cost = calculate_cost(
                prompt_tokens, cached_tokens, completion_tokens,
                input_price, cached_input_price, output_price,
            )
            billed_cost = metrics.get("api_cost") if metrics.get("api_cost") is not None else calculated_cost
            call_detail = {
                "文章序号": sequence, "源表id": article_id, "批次": batch_number, "总批次": len(batches),
                "专题": topic, "平台": row.get("平台"), "本批规则候选单元数": len(batch),
                "请求状态": metrics.get("status"), "HTTP状态": metrics.get("http_status"),
                "输入Token": prompt_tokens, "缓存命中Token": cached_tokens,
                "输出Token": completion_tokens, "总Token": metrics.get("total_tokens"),
                "响应秒数": metrics.get("latency_seconds"), "重试次数": metrics.get("retries"),
                "计价模式": pricing["label"], "输入单价": input_price,
                "缓存输入单价": cached_input_price, "输出单价": output_price,
                "API返回费用": metrics.get("api_cost"), "按配置单价计算费用": calculated_cost,
                "计费费用": billed_cost, "价格来源": PRICING_SOURCE, "价格日期": PRICING_AS_OF,
                "请求ID": metrics.get("request_id"), "错误": metrics.get("error"),
            }
            local_calls.append(call_detail)
            article_metrics.append(call_detail)
        combined_result = {"article_id": article_id, "units": result_units}
        materialized, issues = validate_and_materialize(article_id, topic, candidates, combined_result)
        issues = article_batch_issues + issues
        failures = [x for x in article_metrics if x["请求状态"] != "success"]
        token_value = sum(int(x["总Token"] or 0) for x in article_metrics)
        input_value = sum(int(x["输入Token"] or 0) for x in article_metrics)
        cached_value = sum(int(x["缓存命中Token"] or 0) for x in article_metrics)
        output_value = sum(int(x["输出Token"] or 0) for x in article_metrics)
        known_costs = [x["计费费用"] for x in article_metrics if x["计费费用"] is not None]
        detail = {
            "序号": sequence, "源表id": article_id, "专题": topic, "平台": row.get("平台"),
            "文章标题": row.get("文章标题"), "切片来源": source_type, "来源字符数": len(text),
            "规则候选单元数": len(candidates), "API输出单元数": len(materialized),
            "API调用次数": len(article_metrics), "请求状态": "success" if not failures else "partial_failed",
            "输入Token": input_value, "缓存命中Token": cached_value,
            "输出Token": output_value, "总Token": token_value,
            "响应秒数": round(sum(float(x["响应秒数"] or 0) for x in article_metrics), 3),
            "文章墙钟秒数": round(time.perf_counter() - article_started, 3),
            "费用": round(sum(known_costs), 8) if known_costs else None,
            "计价模式": pricing["label"], "输入单价": input_price,
            "缓存输入单价": cached_input_price, "输出单价": output_price,
            "价格来源": PRICING_SOURCE, "价格日期": PRICING_AS_OF,
            "错误": "；".join(x["错误"] for x in failures if x["错误"]),
            "校验问题": "；".join(issues),
        }
        client.session.close()
        return topic, materialized, local_calls, detail, bool(failures or issues)

    completed = []
    with ThreadPoolExecutor(max_workers=args.concurrency) as executor:
        pending = {executor.submit(process_article, seq, article_id): article_id
                   for seq, article_id in enumerate(sample_ids, 1)}
        for future in as_completed(pending):
            item = future.result()
            completed.append(item)
            detail = item[3]
            print(json.dumps({"progress": f"{len(completed)}/{len(sample_ids)}", "article_id": detail["源表id"], "status": detail["请求状态"], "calls": detail["API调用次数"], "total_tokens": detail["总Token"]}, ensure_ascii=False), flush=True)
    # Deterministic export order, regardless of completion order.
    for topic, materialized, local_calls, detail, needs_review in sorted(completed, key=lambda x: x[3]["序号"]):
        (products if topic == TOPIC1 else viewpoints).extend(materialized)
        calls.extend(local_calls)
        article_costs.append(detail)
        if needs_review:
            reviews.append(detail)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_csv(args.output_dir / "产品信息单元_API.csv", PRODUCT_FIELDS, products)
    write_csv(args.output_dir / "观点信息单元_API.csv", VIEWPOINT_FIELDS, viewpoints)
    call_fields = list(calls[0]) if calls else []
    write_csv(args.output_dir / "API调用明细.csv", call_fields, calls)
    article_fields = list(article_costs[0]) if article_costs else []
    write_csv(args.output_dir / "文章Token成本.csv", article_fields, article_costs)
    write_csv(args.output_dir / "复核队列.csv", article_fields, reviews)
    successful = [x for x in article_costs if x["请求状态"] == "success" and x["总Token"] is not None]
    totals = [int(x["总Token"]) for x in successful]
    priced = [x["费用"] for x in successful if x["费用"] is not None]
    sorted_totals = sorted(totals)
    p90 = sorted_totals[max(0, int(len(sorted_totals) * 0.9 + 0.999999) - 1)] if sorted_totals else None
    summary = {
        "concurrency": args.concurrency,
        "wall_clock_seconds": round(time.perf_counter() - started, 3),
        "all_calls_total_tokens": sum(int(x["总Token"] or 0) for x in calls),
        "all_calls_known_cost": round(sum(float(x["计费费用"]) for x in calls if x["计费费用"] is not None), 8),
        "calls_with_unknown_usage": sum(x["总Token"] is None for x in calls),
        "requested_articles": len(sample_ids), "successful_articles": len(successful),
        "failed_articles": len(article_costs) - len(successful), "api_calls": len(calls), "product_units": len(products),
        "viewpoint_units": len(viewpoints), "total_tokens": sum(totals),
        "average_tokens_per_article": round(statistics.mean(totals), 2) if totals else None,
        "median_tokens_per_article": round(statistics.median(totals), 2) if totals else None,
        "p90_tokens_per_article": p90,
        "average_latency_seconds": round(statistics.mean(x["响应秒数"] for x in successful), 3) if successful else None,
        "total_cost": round(sum(priced), 8) if priced else None,
        "average_cost_per_article": round(statistics.mean(priced), 9) if priced else None,
        "pricing_mode": pricing["label"],
        "input_price_per_million": input_price,
        "cached_input_price_per_million": cached_input_price,
        "output_price_per_million": output_price,
        "pricing_source": PRICING_SOURCE,
        "pricing_as_of": PRICING_AS_OF,
        "pricing_note": "优先采用API返回费用；否则按本地配置单价计算。默认实时价格仅适用于单次输入不超过32K Token。",
        "cost_formula": "(输入Token-缓存命中Token)/1000000×输入单价+缓存命中Token/1000000×缓存输入单价+输出Token/1000000×输出单价",
    }
    (args.output_dir / "api_test_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
