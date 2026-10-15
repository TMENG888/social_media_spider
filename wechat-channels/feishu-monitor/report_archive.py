"""Credential-free archive of acknowledged group reports, not crawler data."""
import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

BEIJING = timezone(timedelta(hours=8))


def archive_confirmed(out, snapshot, db, payload, text, delivered_at, provenance="live_ack"):
    """Call only after a successful Feishu acknowledgment; archive the exact card."""
    from collect import atomic_json
    delivered = datetime.fromtimestamp(delivered_at, timezone.utc)
    digest = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    report_id = f"{int(delivered_at)}-{digest[:16]}"
    folder = Path(out) / "report-history" / delivered.astimezone(BEIJING).strftime("%Y-%m-%d")
    folder.mkdir(parents=True, exist_ok=True)
    entry = {
        "schemaVersion": 1, "reportId": report_id,
        "generatedAt": snapshot.get("generatedAt"),
        "databaseGeneratedAt": db.get("generatedAt"),
        "deliveredAt": delivered.isoformat(), "deliveryConfirmed": True,
        "confirmationProvenance": provenance, "runId": snapshot.get("runId"),
        "sources": {"redis": snapshot.get("sources", {}).get("redis"), "database": db.get("source"),
                    "platforms": {p['platform']: p.get('source') for p in snapshot.get('platformTasks', [])}},
        "payloadSha256": digest, "text": text,
    }
    target = folder / (report_id + ".json")
    if not target.exists():
        atomic_json(target, entry)
    render_recent_day(out, delivered_at)
    return target


def render_recent_day(out, now_seconds):
    """Keep all history; present only delivered reports in the preceding 24 hours."""
    now = datetime.fromtimestamp(now_seconds, timezone.utc)
    cutoff = now - timedelta(hours=24)
    entries = []
    for path in (Path(out) / "report-history").glob("*/*.json"):
        entry = json.loads(path.read_text(encoding="utf-8"))
        delivered = datetime.fromisoformat(entry["deliveredAt"])
        if entry.get("deliveryConfirmed") is True and cutoff <= delivered <= now:
            entries.append(entry)
    entries.sort(key=lambda e: (e["deliveredAt"], e["reportId"]))
    lines = ["# 飞书机器人日报日志｜最近24小时", "",
             "窗口截至：" + now.astimezone(BEIJING).strftime("%Y-%m-%d %H:%M:%S（北京时间）"),
             "仅收录已获飞书发送确认的实际报告。旧历史保留在 report-history；未归档的历史不可补造。",
             "本视图依据已确认的本机发送记录生成；云端更新须单独回读确认，群消息送达不能代替云文档同步确认。",
             "本程序不创建或启用定时任务；发送时间由部署方自行安排。",
             "仅保留实际归档记录，不补造历史。历史不完整时不能计算完整日变化。",
             "重要工作文档请另建知识库页面，不在自动维护的日志中手工编辑。",
             "指标规范：请参阅部署方的团队指标规范文档", ""]
    if not entries:
        lines.append("此窗口暂无可验证的已归档报告；不等于群内没有历史消息。")
    for entry in entries:
        when = datetime.fromisoformat(entry["deliveredAt"]).astimezone(BEIJING)
        lines += ["## " + when.strftime("%Y-%m-%d %H:%M:%S（北京时间）"),
                  "报告ID：" + entry["reportId"],
                  "快照时间：" + str(entry.get("generatedAt") or "未知"),
                  "发送状态：已确认（" + entry.get("confirmationProvenance", "unknown") + "）",
                  "数据源：" + json.dumps(entry.get("sources", {}), ensure_ascii=False), "",
                  entry["text"], ""]
    target = Path(out) / "recent-day-reports.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".md.tmp")
    tmp.write_text("\n".join(lines), encoding="utf-8")
    os.replace(tmp, target)
    # Exact generated body for the dedicated cloud mirror. It never claims its own sync.
    cloud = Path(out) / "cloud-log-body.txt"
    cloud_tmp = cloud.with_suffix(".txt.tmp")
    cloud_tmp.write_text("\n".join(lines[2:]), encoding="utf-8")
    os.replace(cloud_tmp, cloud)
    return entries
