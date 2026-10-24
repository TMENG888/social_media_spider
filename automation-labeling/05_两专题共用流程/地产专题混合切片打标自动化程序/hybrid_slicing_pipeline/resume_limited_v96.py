"""Authorized 20-worker recovery; original generation modules remain unchanged."""
import argparse
import json
import os
import subprocess
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from pathlib import Path
import msvcrt
import resume_missing_v96 as recovery
from safe_concurrency_v96 import Governor, ControlledPost, SoftStop

b, original = recovery.b, recovery.original


def generator_conflicts(output, processes, own_pid):
    target = str(Path(output).resolve()).replace("\\", "/").lower()
    names = ("resume_missing_v96.py", "resume_limited_v96.py", "run_bulk_v96.py")
    return [p["ProcessId"] for p in processes
            if p["ProcessId"] != own_pid and str(p.get("Name", "")).lower().startswith("python")
            and any(n in str(p.get("CommandLine", "")).lower() for n in names)
            and target in str(p.get("CommandLine", "")).replace("\\", "/").lower()]


def assert_no_generator(output):
    script = "[Console]::OutputEncoding=[System.Text.Encoding]::UTF8; Get-CimInstance Win32_Process -Filter \"Name LIKE 'python%'\" | Select-Object ProcessId,Name,CommandLine | ConvertTo-Json -Compress"
    result = subprocess.run(["powershell.exe", "-NoProfile", "-Command", script],
                            check=True, capture_output=True, text=True, encoding="utf-8",
                            creationflags=subprocess.CREATE_NO_WINDOW)
    processes = json.loads(result.stdout) if result.stdout.strip() else []
    if isinstance(processes, dict):
        processes = [processes]
    conflicts = generator_conflicts(output, processes, os.getpid())
    if conflicts:
        raise RuntimeError("Another generator is active for this exact directory: " + str(conflicts))


class InstanceLock:
    def __init__(self, directory):
        self.path = directory / "limited_recovery.lock"
        self.file = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.file = self.path.open("a+b")
        self.file.seek(0, 2)
        if self.file.tell() == 0:
            self.file.write(b"0")
            self.file.flush()
        self.file.seek(0)
        try:
            msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            self.file.close()
            raise RuntimeError("Another limited recovery owns the single-instance lock")
        return self

    def __exit__(self, *args):
        self.file.seek(0)
        msvcrt.locking(self.file.fileno(), msvcrt.LK_UNLCK, 1)
        self.file.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample", type=Path, required=True)
    parser.add_argument("--taxonomy", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--concurrency", type=int, default=20, choices=range(1, 21))
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--run", action="store_true")
    args = parser.parse_args()
    documents = json.loads(args.sample.read_text(encoding="utf-8"))["documents"]
    ids = [d["record_id"] for d in documents]
    assert len(ids) == len(set(ids)) == 1956
    assert Counter((d["topic"], d["kind"]) for d in documents) == Counter(
        {(b.T1, "文章"): 500, (b.T2, "文章"): 500, (b.T2, "评论"): 956})
    taxonomy, business = b.load_taxonomy(args.taxonomy), b.load_business()
    assert "无需具体器械" in next(t for t in taxonomy if t["tag_id"] == "VOC-0377")["instruction"]
    signature = recovery.original_signature(taxonomy, business)
    if not args.run:
        manifest = recovery.inventory(args.output_dir, documents, signature, taxonomy)
        print(b.dumps({"dry_run": True, **{k: v for k, v in manifest.items()
              if k not in {"complete_ids", "missing_ids", "original_signature"}}}), flush=True)
        return
    control_dir = args.output_dir / "recovery_v96" / "limited"
    with InstanceLock(control_dir):
        assert_no_generator(args.output_dir)
        manifest = recovery.inventory(args.output_dir, documents, signature, taxonomy)
        key = os.getenv("YS_LLM_API_KEY")
        if not key:
            raise RuntimeError("YS_LLM_API_KEY is not configured; do not print it")
        assert_no_generator(args.output_dir)
        stop_path = control_dir / "soft_stop.request"
        if stop_path.exists():
            raise SoftStop("Existing soft-stop marker retained; no new HTTP attempt sent")
        original.mr.activate()
        runner = original.BulkRunner(args.output_dir, 10, key=key)
        # Replace only this new instance's semaphore. No original code changes.
        runner.gate = threading.BoundedSemaphore(args.concurrency)
        governor = Governor(args.concurrency, stop=lambda: stop_path.exists() or runner.fatal.is_set())
        old_post = b.post_json
        b.post_json = ControlledPost(old_post, governor, control_dir, b.save_json)
        api = json.loads((args.output_dir / "api_progress.json").read_text(encoding="utf-8"))
        single = json.loads((args.output_dir / "single_unit_progress.json").read_text(encoding="utf-8"))
        runner.counter = api["calls_seen"]
        runner.scope_count, runner.scans = single["single_unit_requests"], single["completed_scan_requests"]
        b.save_json(control_dir / "checkpoint_inventory.json", manifest)
        b.save_json(control_dir / "launcher_identity.json", {
            "pid": os.getpid(), "started_at": time.time(), "script": str(Path(__file__).resolve()),
            "output_dir": str(args.output_dir.resolve()), "core_code_modified": False,
            "concurrency": args.concurrency, "original_signature": signature,
            "soft_stop_marker": str(stop_path), "auto_export_enabled": False})
        by_id = {d["record_id"]: d for d in documents}
        complete, recovered, failures, interrupted = set(manifest["complete_ids"]), [], [], []
        pending_ids = iter(manifest["missing_ids"])
        started = time.time()

        def progress(status, latest=None):
            selected = [by_id[i] for i in complete]
            stats = {"processed_sources": len(complete), "planned_sources": len(documents),
                     "processed_articles": Counter(d["topic"] for d in selected if d["kind"] == "文章"),
                     "processed_comments": sum(d["kind"] == "评论" for d in selected),
                     "elapsed_seconds": round(time.time() - started), "latest_record_id": latest,
                     "mode": "limited_checkpoint_recovery_v96", "qualification_pending": True}
            report = {**stats, "status": status, "recovery_pid": os.getpid(),
                      "preserved_final_sources": manifest["preserved_final_sources"],
                      "recovered_sources": len(recovered), "failed_sources": len(failures),
                      "failures": failures, "interrupted_sources": interrupted,
                      "concurrency": governor.snapshot(), "updated_at": time.time()}
            b.save_json(args.output_dir / "bulk_progress.json", stats)
            b.save_json(args.output_dir / "recovery_progress.json", report)
            print(b.dumps({k: v for k, v in report.items() if k not in {"failures", "interrupted_sources"}}), flush=True)

        progress("recovering_missing_sources")
        try:
            with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
                futures = {}

                def fill():
                    while len(futures) < args.concurrency and not governor.stop():
                        source = next(pending_ids, None)
                        if source is None:
                            break
                        future = pool.submit(recovery.recover, by_id[source], args.output_dir,
                                             signature, taxonomy, business, runner)
                        futures[future] = source

                fill()
                while futures:
                    done, _ = wait(futures, timeout=5, return_when=FIRST_COMPLETED)
                    for future in done:
                        source = futures.pop(future)
                        try:
                            result = future.result()
                            assert result["document"]["record_id"] == source
                            complete.add(source)
                            recovered.append(source)
                        except SoftStop:
                            interrupted.append(source)
                        except Exception as exc:
                            failures.append({"record_id": source, "error_type": type(exc).__name__,
                                             "error": str(exc).replace(key, "[REDACTED]")[:2000]})
                        progress("recovering_missing_sources" if not failures else
                                 "recovering_with_recorded_source_errors", source)
                    fill()
            status = ("all_source_checkpoints_saved_pending_remediation" if len(complete) == len(documents)
                      and not failures else "soft_stopped_checkpoint_recovery" if governor.stop()
                      else "source_recovery_needs_attention")
            progress(status)
        finally:
            b.post_json = old_post
        if failures:
            raise SystemExit(1)


if __name__ == "__main__":
    main()
