"""Recover only missing v96 source/stage checkpoints without changing core code."""
import argparse
import copy
import json
import os
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import run_bulk_v96 as original

b = original.b
STAGES = ("01_mapreduce", "02_D_H", "03_single_unit", "04_final")
SIGNATURE_FILES = (
    "run_bulk_v96.py", "gym_policy_v96.py", "keyword_supplement_v94.py",
    "joint_keyword_supplement_v95.py", "full_dictionary_supplement_v92.py",
    "label_definition_precision.py",
)


def original_signature(taxonomy, business):
    implementation = {
        name: Path(original.__file__).with_name(name).read_text(encoding="utf-8")
        for name in SIGNATURE_FILES
    }
    return b.digest({"version": original.VERSION, "policy": original.POLICY_VERSION,
                     "code": implementation, "taxonomy": taxonomy, "business": business})


def stage_path(output, stage, document):
    return output / "stages" / stage / (b.digest(document["record_id"]) + ".json")


def expected_signature(signature, document, prior):
    return b.digest({"code": signature, "document": document, "input": prior})


def read_checkpoint(output, stage, document, signature, prior):
    path = stage_path(output, stage, document)
    saved = json.loads(path.read_text(encoding="utf-8"))
    if saved.get("bulk_signature") != expected_signature(signature, document, prior):
        raise RuntimeError("Existing checkpoint signature differs; retained without overwrite: "
                           + document["record_id"] + "/" + stage)
    result = saved["result"]
    # The original pipeline appends semantic_segments/project policy metadata.
    # Every original source field must remain exact; added pipeline metadata
    # does not change the frozen source represented by this checkpoint.
    if any(result["document"].get(key) != value for key, value in document.items()):
        raise RuntimeError("Existing checkpoint document differs: " + document["record_id"])
    return result


def inventory(output, documents, signature, taxonomy):
    complete, missing, counts = [], [], Counter()
    for index, document in enumerate(documents, 1):
        prior, gap = None, False
        for stage in STAGES:
            if not stage_path(output, stage, document).exists():
                gap = True
                continue
            if gap:
                raise RuntimeError("Orphaned later-stage checkpoint retained: "
                                   + document["record_id"] + "/" + stage)
            prior = read_checkpoint(output, stage, document, signature, prior)
            counts[stage] += 1
        if stage_path(output, "04_final", document).exists():
            original.validate_final(prior, taxonomy)
            complete.append(document["record_id"])
        else:
            missing.append(document["record_id"])
        if index % 100 == 0:
            print(b.dumps({"inventory_checked": index, "planned_sources": len(documents),
                           "api_requests_sent": 0}), flush=True)
    return {"passed": True, "planned_sources": len(documents),
            "preserved_final_sources": len(complete), "missing_final_sources": len(missing),
            "stage_counts": dict(counts), "complete_ids": complete, "missing_ids": missing,
            "original_signature": signature, "api_requests_sent_during_inventory": 0}


def checkpoint(output, stage, document, signature, prior, function):
    path = stage_path(output, stage, document)
    if path.exists():
        return read_checkpoint(output, stage, document, signature, prior)
    result = function()
    if path.exists():
        raise RuntimeError("Concurrent checkpoint creation detected: " + str(path))
    b.save_json(path, {"bulk_signature": expected_signature(signature, document, prior),
                       "result": result})
    return result


def recover(document, output, signature, taxonomy, business, runner):
    if runner.fatal.is_set():
        raise RuntimeError("API authentication failed; no new source request sent")
    core = checkpoint(output, "01_mapreduce", document, signature, None,
                      lambda: original.mr.process_document(document, taxonomy, business, runner))
    refined = checkpoint(output, "02_D_H", document, signature, core,
                         lambda: original.h_context(core, taxonomy, runner))
    recalled = checkpoint(output, "03_single_unit", document, signature, refined,
                          lambda: original.s.process(refined, taxonomy, business, runner,
                                                     output, 48, "single_unit"))

    def finish():
        result = original.guard_new(copy.deepcopy(recalled), refined, taxonomy)
        result = original.joint.process(result, taxonomy)
        result = original.repair_content_fields(result, taxonomy, business, runner)
        result = original.projects.process(result, business, runner)
        result["bulk_policy_version"] = original.POLICY_VERSION
        return original.validate_final(result, taxonomy)

    return checkpoint(output, "04_final", document, signature, recalled, finish)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample", type=Path, required=True)
    parser.add_argument("--taxonomy", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--run", action="store_true")
    args = parser.parse_args()
    documents = json.loads(args.sample.read_text(encoding="utf-8"))["documents"]
    ids = [document["record_id"] for document in documents]
    assert len(ids) == len(set(ids)) == 1956
    assert Counter((d["topic"], d["kind"]) for d in documents) == Counter(
        {(b.T1, "文章"): 500, (b.T2, "文章"): 500, (b.T2, "评论"): 956})
    taxonomy, business = b.load_taxonomy(args.taxonomy), b.load_business()
    assert "无需具体器械" in next(t for t in taxonomy if t["tag_id"] == "VOC-0377")["instruction"]
    signature = original_signature(taxonomy, business)
    manifest = inventory(args.output_dir, documents, signature, taxonomy)
    brief = {key: value for key, value in manifest.items()
             if key not in ("complete_ids", "missing_ids", "original_signature")}
    print(b.dumps({"inventory": brief, "dry_run": not args.run}), flush=True)
    if not args.run:
        return
    key = os.getenv("YS_LLM_API_KEY")
    if not key:
        raise RuntimeError("YS_LLM_API_KEY is not configured; do not print it")
    original.mr.activate()
    runner = original.BulkRunner(args.output_dir, 10, key=key)
    api_progress = json.loads((args.output_dir / "api_progress.json").read_text(encoding="utf-8"))
    single_progress = json.loads((args.output_dir / "single_unit_progress.json").read_text(encoding="utf-8"))
    runner.counter = api_progress["calls_seen"]
    runner.scope_count = single_progress["single_unit_requests"]
    runner.scans = single_progress["completed_scan_requests"]
    b.save_json(args.output_dir / "recovery_v96" / "checkpoint_inventory.json", manifest)
    by_id = {document["record_id"]: document for document in documents}
    complete, failures, recovered = set(manifest["complete_ids"]), [], []
    started = time.time()

    def progress(status, latest=None):
        selected = [by_id[source_id] for source_id in complete]
        stats = {
            "processed_sources": len(complete), "planned_sources": len(documents),
            "processed_articles": Counter(d["topic"] for d in selected if d["kind"] == "文章"),
            "processed_comments": sum(d["kind"] == "评论" for d in selected),
            "elapsed_seconds": round(time.time() - started), "latest_record_id": latest,
            "mode": "checkpoint_recovery_v96", "qualification_pending": True,
        }
        report = {**stats, "status": status, "recovery_pid": os.getpid(),
                  "preserved_final_sources": manifest["preserved_final_sources"],
                  "recovered_sources": len(recovered), "failed_sources": len(failures),
                  "failures": failures, "updated_at": time.time()}
        b.save_json(args.output_dir / "bulk_progress.json", stats)
        b.save_json(args.output_dir / "recovery_progress.json", report)
        print(b.dumps({key: value for key, value in report.items() if key != "failures"}), flush=True)

    progress("recovering_missing_sources")
    with ThreadPoolExecutor(max_workers=10) as pool:
        futures = {pool.submit(recover, by_id[source_id], args.output_dir, signature,
                               taxonomy, business, runner): source_id
                   for source_id in manifest["missing_ids"]}
        for future in as_completed(futures):
            source_id = futures[future]
            try:
                result = future.result()
                assert result["document"]["record_id"] == source_id
                complete.add(source_id)
                recovered.append(source_id)
                progress("recovering_missing_sources", source_id)
            except Exception as error:
                failures.append({"record_id": source_id, "error_type": type(error).__name__,
                                 "error": str(error).replace(key, "[REDACTED]")[:2000]})
                progress("recovering_with_recorded_source_errors", source_id)
    final_status = ("all_source_checkpoints_saved_pending_remediation"
                    if len(complete) == len(documents) and not failures
                    else "source_recovery_needs_attention")
    progress(final_status)
    # Post-generation semantic/API remediation and independent workbook
    # verification remain required; recovery never exports automatically.
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
