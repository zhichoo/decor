#!/usr/bin/env python3
"""Resumable transcript-only backfill and ad review. Never extracts/deletes claims."""
import argparse
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
import server


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backfill", action="store_true")
    parser.add_argument("--include-placeholders", action="store_true")
    parser.add_argument("--review-existing", action="store_true")
    parser.add_argument("--delay-seconds", type=float, default=3, help="Pause between model requests (default: 3)")
    args = parser.parse_args()
    if not (args.backfill or args.review_existing):
        parser.error("choose --backfill or --review-existing")
    out = ROOT / ".runtime/ad-review"
    out.mkdir(parents=True, exist_ok=True, mode=0o700)
    report = out / ("run-" + time.strftime("%Y%m%d-%H%M%S") + ".jsonl")
    with server.connect() as conn:
        rows = conn.execute("SELECT * FROM videos WHERE deleted_at IS NULL ORDER BY created_at, id").fetchall()
    for index, row in enumerate(rows, 1):
        text = (row["transcript_text"] or "").strip()
        placeholder = bool(text) and text == (row["title"] or "").strip()
        needs_text = not text or (args.include_placeholders and placeholder)
        if not ((args.backfill and needs_text) or args.review_existing):
            continue
        cached = server.advertising.current_review(row)
        needs_review = bool(text) and (not cached or cached.get("decision") == "error")
        item = {"id": row["id"], "title": row["title"], "index": index, "total": len(rows)}
        try:
            with server.connect() as conn:
                if args.backfill and needs_text:
                    video, _ = server.save_transcript_for_video(conn, row, refresh=placeholder)
                    item["transcript"] = "saved"
                review = server.review_video_advertising(conn, row["id"])
                item.update(state="completed", review=review)
        except Exception as exc:
            item.update(state="failed", error=server.truncate_error(str(exc)))
        line = json.dumps(item, ensure_ascii=False)
        with report.open("a", encoding="utf-8") as stream:
            stream.write(line + "\n")
        print(line, flush=True)
        review = item.get("review") or {}
        if review.get("error_code") == "deepseek_http_429":
            time.sleep(max(65, args.delay_seconds))
        elif needs_review or (args.backfill and needs_text):
            time.sleep(max(0, args.delay_seconds))
    print("Report: " + str(report), flush=True)


if __name__ == "__main__":
    main()
