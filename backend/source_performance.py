"""Read-only source maintenance signals, not author credibility or factual accuracy."""
from collections import Counter, defaultdict
import hashlib

import advertising


WINDOW = 10
CONTENT_LABELS = {"not_ad": "普通", "advertising": "推广", "uncertain": "存疑",
                  "error": "判定失败", "unknown": "未判定"}
OUTCOME_LABELS = {
    "completed": "已完成提取", "filtered": "未收录内容", "pending": "待提取观点",
    "transcript_pending": "待获取文案", "asr_failed": "文案获取失败",
    "classification_failed": "推广判定服务失败", "model_failed": "模型调用失败",
    "format_failed": "证据或格式校验失败", "storage_failed": "入库失败",
    "in_progress": "提取未完成", "stale": "文案已变，结果过期",
    "blocked": "推广或存疑，未自动提取",
}
TECHNICAL_OUTCOMES = {"asr_failed", "classification_failed", "model_failed", "format_failed",
                      "storage_failed", "in_progress"}
REASON_LABELS = {"parameter": "参数不清", "reference": "指代或范围不清", "promotion": "推广关联",
                 "thin": "信息过少或重复", "transcription": "文案不清", "attitude": "立场不清",
                 "evidence": "证据不足", "other": "其他已记录排除"}


def reason_category(item):
    issues = item.get("issues") or []
    types = {issue.get("type") for issue in issues if isinstance(issue, dict)}
    text = str(item.get("reason") or "").lower()
    if any(word in text for word in ("promotion", "brand_model", "推广", "产品链", "品牌型号")):
        return "promotion"
    if "parameter" in types or any(word in text for word in ("parameter", "measurement", "numeric", "参数", "尺寸", "价格不清", "价格口播")):
        return "parameter"
    if "scope" in types or any(word in text for word in ("reference", "scope", "指代", "画面", "范围")):
        return "reference"
    if "transcription" in types or any(word in text for word in ("speech_unclear", "识别错误", "口播不清", "文案不清")):
        return "transcription"
    if "attitude" in types:
        return "attitude"
    if any(word in text for word in ("thin", "duplicate", "fragment", "空泛", "碎片", "重复", "无实际信息")):
        return "thin"
    return "evidence" if "evidence" in types else "other"


def extraction_outcome(video, run, review, has_history):
    if video.get("status") == "transcript_failed":
        return "asr_failed"
    if not (video.get("transcript_text") or "").strip():
        return "transcript_pending"
    if run:
        status = run["status"]
        if status in ("completed", "filtered"):
            return "filtered" if video.get("status") == "claims_filtered" else status
        if status == "request_started":
            return "in_progress"
        if status in ("parse_failed", "quality_check_failed"):
            return "format_failed"
        return "storage_failed" if status == "insert_failed" else "model_failed"
    if review.get("decision") == "error":
        return "classification_failed"
    if has_history:
        return "stale"
    if review.get("decision") in ("advertising", "uncertain"):
        return "blocked"
    return "pending"


def summarize_video(video, claims, runs, prompt_version):
    digest = hashlib.sha256((video.get("transcript_text") or "").encode()).hexdigest()
    ordered = sorted(runs, key=lambda row: (row["created_at"], row["id"]), reverse=True)
    run = next((row for row in ordered if row["input_hash"] == digest), None)
    by_run = {row["id"]: row for row in runs}
    review = advertising.current_review(video)
    decision = review.get("decision")
    decision = decision if decision in CONTENT_LABELS else "unknown"
    outcome = extraction_outcome(video, run, review, bool(runs))
    versions = Counter({"current": 0, "legacy": 0, "stale": 0, "untracked": 0})
    deletions = Counter({"quality_cleanup": 0, "replacement": 0, "other": 0})
    cleanup_reasons = Counter()
    for card in claims:
        if card.get("deleted_at") is not None:
            reason = card.get("delete_reason") or ""
            if card.get("deleted_by") == "system" and reason == "replace_extracted_claims":
                deletions["replacement"] += 1
            elif card.get("deleted_by") == "system" and reason.startswith("incremental_quality_cleanup:"):
                deletions["quality_cleanup"] += 1
                cleanup_reasons[reason_category({"reason": reason})] += 1
            else:
                deletions["other"] += 1
            continue
        lineage = by_run.get(card.get("extraction_run_id"))
        version = "untracked" if not lineage else (
            "stale" if lineage["input_hash"] != digest else
            "current" if lineage["prompt_version"] == prompt_version else "legacy")
        versions[version] += 1
    exclusions = Counter()
    optional_omissions = 0
    if run and not (run.get("review_data") or {}).get("superseded"):
        for item in (run.get("review_data") or {}).get("items") or []:
            if not isinstance(item, dict):
                continue
            if item.get("reason") == "unsupported_optional_field":
                optional_omissions += 1
            else:
                exclusions[reason_category(item)] += 1
    published = video.get("published_at_ts")
    filtered_reason = None
    if outcome == "filtered":
        message = video.get("last_error") or ""
        filtered_reason = REASON_LABELS[reason_category({"reason": message})] if message.startswith("无有效内容") else None
    return {
        "id": video["id"], "title": video["title"],
        "published_at": published.isoformat() if published else None,
        "deleted": video.get("deleted_at") is not None,
        "content": decision, "content_label": CONTENT_LABELS[decision],
        "decision_source": "manual" if review.get("source") == "manual" else "automatic" if review else "none",
        "outcome": outcome, "outcome_label": OUTCOME_LABELS[outcome],
        "technical_issue": outcome in TECHNICAL_OUTCOMES or decision == "error",
        "run_version": ("current" if run["prompt_version"] == prompt_version else "legacy") if run else None,
        "retained_cards": sum(versions.values()), "card_versions": dict(versions),
        "deletions": dict(deletions), "exclusions": dict(exclusions),
        "cleanup_reasons": dict(cleanup_reasons), "optional_omissions": optional_omissions,
        "filtered_reason": filtered_reason,
    }


def summarize_source(source_id, videos, claims, runs, prompt_version):
    by_video_claims, by_video_runs = defaultdict(list), defaultdict(list)
    for card in claims:
        by_video_claims[card["video_id"]].append(card)
    for run in runs:
        by_video_runs[run["video_id"]].append(run)
    items = [summarize_video(video, by_video_claims[video["id"]], by_video_runs[video["id"]], prompt_version)
             for video in videos]
    content = Counter({key: 0 for key in CONTENT_LABELS})
    outcomes, versions, deletions, exclusions, cleanup_reasons = (Counter() for _ in range(5))
    for item in items:
        content[item["content"]] += 1
        outcomes[item["outcome"]] += 1
        versions.update(item["card_versions"])
        deletions.update(item["deletions"])
        exclusions.update(item["exclusions"])
        cleanup_reasons.update(item["cleanup_reasons"])
    dates = [item["published_at"] for item in items if item["published_at"]]
    return {
        "source_id": source_id, "sample_count": len(items), "window": WINDOW,
        "deleted_videos": sum(item["deleted"] for item in items),
        "published_from": min(dates) if dates else None, "published_to": max(dates) if dates else None,
        "undated_videos": sum(not item["published_at"] for item in items),
        "content_counts": dict(content), "outcome_counts": dict(outcomes),
        "videos_with_cards": sum(item["retained_cards"] > 0 for item in items),
        "retained_cards": sum(item["retained_cards"] for item in items),
        "card_versions": dict(versions), "deletions": dict(deletions),
        "technical_videos": sum(item["technical_issue"] for item in items),
        "current_completed": sum(item["run_version"] == "current" and item["outcome"] in ("completed", "filtered") for item in items),
        "exclusions": dict(exclusions), "cleanup_reasons": dict(cleanup_reasons),
        "optional_omissions": sum(item["optional_omissions"] for item in items), "videos": items,
    }


def fetch_performance(conn, prompt_version):
    # Rank before considering deletion; otherwise deleting ads improves the apparent sample.
    with conn.transaction():
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        sources = conn.execute("SELECT id FROM sources ORDER BY created_at DESC, id").fetchall()
        videos = conn.execute("""SELECT * FROM (
            SELECT v.*, ROW_NUMBER() OVER (PARTITION BY source_id
                ORDER BY published_at_ts DESC NULLS LAST, created_at DESC, id DESC) AS sample_rank
            FROM videos v WHERE source_id IN (SELECT id FROM sources)
        ) ranked WHERE sample_rank <= %s ORDER BY source_id, sample_rank""", (WINDOW,)).fetchall()
        ids = [video["id"] for video in videos]
        claims = conn.execute("""SELECT video_id, extraction_run_id, deleted_at, deleted_by, delete_reason
            FROM claims WHERE video_id = ANY(%s)""", (ids,)).fetchall() if ids else []
        runs = conn.execute("""SELECT id, video_id, prompt_version, input_hash, status, created_at, review_data
            FROM extraction_runs WHERE video_id = ANY(%s)""", (ids,)).fetchall() if ids else []
    by_source, by_video_claims, by_video_runs = defaultdict(list), defaultdict(list), defaultdict(list)
    for video in videos:
        by_source[video["source_id"]].append(video)
    for card in claims:
        by_video_claims[card["video_id"]].append(card)
    for run in runs:
        by_video_runs[run["video_id"]].append(run)
    return {"window": WINDOW, "prompt_version": prompt_version, "reason_labels": REASON_LABELS,
            "sources": [summarize_source(source["id"], by_source[source["id"]],
                        [card for video in by_source[source["id"]] for card in by_video_claims[video["id"]]],
                        [run for video in by_source[source["id"]] for run in by_video_runs[video["id"]]],
                        prompt_version) for source in sources]}
