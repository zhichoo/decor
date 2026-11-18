#!/usr/bin/env python3
"""Read-only inventory and resumable, file-only model trials for claim upgrades."""
import argparse
from collections import Counter, defaultdict
from contextlib import closing
import hashlib
import json
import os
import re
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
import advertising
import claim_contract

TABLES = ("sources", "videos", "claims", "extraction_runs")
SUCCESS = ("completed", "filtered")


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     default=str, separators=(",", ":")).encode()).hexdigest()


def text_hash(text):
    return hashlib.sha256((text or "").encode()).hexdigest()


def save_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as output:
        os.chmod(temporary, 0o600)
        json.dump(value, output, ensure_ascii=False, indent=2, default=str)
        output.write("\n")
    temporary.replace(path)


def read_database(dsn):
    import psycopg2
    from psycopg2.extras import RealDictCursor

    with closing(psycopg2.connect(dsn, connect_timeout=10, cursor_factory=RealDictCursor)) as conn:
        conn.set_session(readonly=True, isolation_level="REPEATABLE READ")
        with conn.cursor() as cursor:
            cursor.execute("SET LOCAL statement_timeout = '30s'")
            return {table: _read_table(cursor, table) for table in TABLES}


def _read_table(cursor, table):
    cursor.execute("SELECT * FROM public." + table + " ORDER BY id")
    return [dict(row) for row in cursor.fetchall()]


def signatures(snapshot):
    return {table: {"count": len(snapshot[table]), "sha256": digest(snapshot[table])} for table in TABLES}


def deletion_guard(claim):
    return claim.get("deleted_at") is not None and not (
        claim.get("deleted_by") == "system" and claim.get("delete_reason") == "replace_extracted_claims")


def has_stored_evidence(claim, transcript):
    try:
        claim_contract.validate_stored_evidence(claim, transcript)
        return True
    except (ValueError, TypeError, KeyError):
        return False


def inventory(snapshot, version, minimum_length=120):
    runs = {run["id"]: run for run in snapshot["extraction_runs"]}
    by_video, history = defaultdict(list), defaultdict(list)
    for claim in snapshot["claims"]:
        by_video[claim["video_id"]].append(claim)
    for run in runs.values():
        history[run["video_id"]].append(run)
    records = []
    versions = Counter()
    for video in snapshot["videos"]:
        related = by_video[video["id"]]
        active = [claim for claim in related if claim.get("deleted_at") is None]
        transcript = video.get("transcript_text") or ""
        input_hash = text_hash(transcript)
        review = advertising.current_review(video)
        applicable = [run for run in history[video["id"]]
                      if run.get("input_hash") == input_hash and run.get("status") in SUCCESS]
        applicable.sort(key=lambda run: (run.get("created_at") or 0, run["id"]), reverse=True)
        current_run = next((run for run in applicable if run.get("prompt_version") == version), None)
        card_versions = Counter(runs.get(claim.get("extraction_run_id"), {}).get("prompt_version") or "legacy_unknown"
                                for claim in active)
        if video.get("deleted_at") is not None:
            state = "deleted_video"
        elif not transcript.strip() or transcript.strip() == (video.get("title") or "").strip():
            state = "missing_transcript"
        elif len(re.sub(r"[\W_]+", "", transcript)) < 6:
            state = "short_transcript"
        elif any(deletion_guard(claim) for claim in related):
            # Block the whole video rather than guessing semantic matches to deleted cards.
            state = "deletion_guard"
        elif review.get("decision") != "not_ad":
            state = "advertising" if review.get("decision") == "advertising" else "ad_status_unresolved"
        elif active and all(runs.get(claim.get("extraction_run_id"), {}).get("prompt_version") == version
                            and runs.get(claim.get("extraction_run_id"), {}).get("video_id") == video["id"]
                            and runs.get(claim.get("extraction_run_id"), {}).get("input_hash") == input_hash
                            and claim.get("source_quotes") and claim.get("author_stance") and claim.get("content_type")
                            and has_stored_evidence(claim, transcript)
                            for claim in active):
            state = "current"
        elif not active and current_run:
            state = "current_filtered"
        else:
            state = "outdated"
        if video.get("deleted_at") is None:
            versions.update(card_versions)
        records.append({"video_id": video["id"], "title": video.get("title"), "creator": video.get("creator"),
                        "state": state, "ad_decision": review.get("decision") or "unknown",
                        "transcript_length": len(transcript), "input_hash": input_hash,
                        "active_claims": len(active), "claim_versions": dict(card_versions),
                        "missing_quotes": sum(not claim.get("source_quotes") for claim in active),
                        "missing_context": sum(not claim.get("author_stance") or not claim.get("content_type") for claim in active),
                        "protected_deleted_claims": sum(deletion_guard(claim) for claim in related),
                        "latest_success_version": applicable[0].get("prompt_version") if applicable else None})
    return {"prompt_version": version, "created_at": int(time.time()), "signatures": signatures(snapshot),
            "states": dict(Counter(record["state"] for record in records)),
            "active_claim_versions": dict(versions), "videos": records}


def choose_samples(audit, limit=8, exclude_ids=()):
    if not 5 <= limit <= 10:
        raise ValueError("sample size must be between 5 and 10")
    candidates = [row for row in audit["videos"] if row["state"] == "outdated" and row["video_id"] not in exclude_ids]
    controls = [row for row in audit["videos"] if row["state"] == "advertising" and row["video_id"] not in exclude_ids]
    selected, creators = [], Counter()
    # Reserve up to two advertising controls; calls only create private trial files.
    for pool, count in ((candidates, limit - min(2, len(controls))), (controls, min(2, len(controls)))):
        for _ in range(count):
            available = [row for row in pool if row not in selected]
            if not available:
                break
            row = min(available, key=lambda item: (creators[item["creator"]],
                -bool(item["active_claims"]), -bool(item["missing_quotes"]),
                digest(["claim-upgrade-sample-v1", item["video_id"]])))
            selected.append(row)
            creators[row["creator"]] += 1
    return selected


def evaluate_response(server, raw, transcript, video=None):
    extracted = server.parse_deepseek_content(raw)
    if not isinstance(extracted, dict) or not isinstance(extracted.get("claims"), list):
        raise ValueError("deepseek_invalid_claims_shape")
    claims, dropped, excluded = server.partition_claims(extracted, transcript, require_contract=True, video=video)
    if not claims and not excluded:
        if extracted["claims"] or extracted.get("filter_reason") not in server.FILTER_REASON_MESSAGES:
            raise ValueError("quality_check_failed")
    return {"status": "completed" if claims else "filtered", "claims": claims, "dropped": dropped,
            "excluded": excluded, "filter_reason": extracted.get("filter_reason"),
            "filter_message": extracted.get("filter_message"), "raw_claim_count": len(extracted["claims"])}


def stage_sample(workspace, server, limit=8, selection_from=None, exclude_from=None):
    workspace = Path(workspace)
    snapshot = json.loads((workspace / "snapshot.private.json").read_text())
    audit = json.loads((workspace / "inventory.json").read_text())
    if audit["prompt_version"] != server.PROMPT_VERSION or audit["signatures"] != signatures(snapshot):
        raise ValueError("inventory version or snapshot changed; audit again")
    if selection_from and exclude_from:
        raise ValueError("selection-from and exclude-from are mutually exclusive")
    if selection_from:
        previous = json.loads(Path(selection_from).read_text())
        by_id = {row["video_id"]: row for row in audit["videos"]}
        if not 5 <= limit <= 10 or len(previous) != limit or len({row["video_id"] for row in previous}) != limit:
            raise ValueError("invalid previous sample selection")
        selected = []
        for row in previous:
            current = by_id.get(row["video_id"])
            if (not current or current["state"] not in ("outdated", "advertising")
                    or current["input_hash"] != row["input_hash"] or current["ad_decision"] != row["ad_decision"]):
                raise ValueError("previous sample input or eligibility changed")
            selected.append(current)
    else:
        excluded_ids = {row["video_id"] for row in json.loads(Path(exclude_from).read_text())} if exclude_from else set()
        selected = choose_samples(audit, limit, excluded_ids)
    if len(selected) < 5:
        raise ValueError("fewer than five eligible samples; inspect inventory")
    videos = {video["id"]: video for video in snapshot["videos"]}
    selection_path = workspace / "sample-selection.json"
    if selection_path.exists() and json.loads(selection_path.read_text()) != selected:
        raise ValueError("sample selection changed; use a new workspace")
    save_json(selection_path, selected)
    results = []
    for row in selected:
        video = videos[row["video_id"]]
        prompt = server.build_extract_prompt(video)
        fingerprint = digest([server.PROMPT_VERSION, server.active_model_name(), prompt])
        path = workspace / "samples" / (video["id"] + ".json")
        if path.exists():
            saved = json.loads(path.read_text())
            if saved.get("fingerprint") != fingerprint:
                raise ValueError("sample prompt changed; use a new workspace")
            results.append(saved)
            continue
        started = time.monotonic()
        result = {"video_id": video["id"], "creator": video["creator"], "title": video["title"],
                  "fingerprint": fingerprint, "prompt_version": server.PROMPT_VERSION,
                  "input_hash": row["input_hash"], "ad_decision": row["ad_decision"],
                  "old_claim_count": row["active_claims"], "model": server.active_model_name(),
                  "model_calls": 1, "created_at": int(time.time())}
        # Write intent first: an interrupted request must not silently be billed again.
        save_json(path, result | {"status": "request_started_unknown_result"})
        print(json.dumps({"stage": "extracting", "video_id": video["id"], "creator": video["creator"]}, ensure_ascii=False), flush=True)
        raw, error = server.call_deepseek(prompt)
        if error or not raw:
            result.update(status="model_failed", error=error or "empty_response")
        else:
            result["raw_response"] = raw
            try:
                response = json.loads(raw)
                result["usage"] = response.get("usage", {}) if isinstance(response, dict) else {}
            except (ValueError, TypeError):
                result["usage"] = {}
            try:
                result.update(evaluate_response(server, raw, video["transcript_text"], video))
            except (ValueError, TypeError, KeyError) as exc:
                result.update(status="validation_failed", error=str(exc)[:500])
        result["seconds"] = round(time.monotonic() - started, 1)
        save_json(path, result)
        results.append(result)
        print(json.dumps({"stage": "result", "video_id": video["id"], "status": result["status"],
                          "old": row["active_claims"], "new": len(result.get("claims", []))}, ensure_ascii=False), flush=True)
    summary = {"prompt_version": server.PROMPT_VERSION, "sample_count": len(results),
               "statuses": dict(Counter(result["status"] for result in results)),
               "old_claims": sum(result["old_claim_count"] for result in results),
               "new_claims": sum(len(result.get("claims", [])) for result in results),
               "production_writes": 0, "gate": "not_evaluated"}
    save_json(workspace / "sample-summary.json", summary)
    return summary


def recheck_samples(workspace, server):
    """Re-evaluate saved responses, never repeat the paid request or mutate its record."""
    workspace = Path(workspace)
    snapshot = json.loads((workspace / "snapshot.private.json").read_text())
    videos = {video["id"]: video for video in snapshot["videos"]}
    selection = json.loads((workspace / "sample-selection.json").read_text())
    results = []
    for row in selection:
        saved = json.loads((workspace / "samples" / (row["video_id"] + ".json")).read_text())
        video = videos[row["video_id"]]
        if saved["input_hash"] != text_hash(video.get("transcript_text")) or saved["input_hash"] != row["input_hash"]:
            raise ValueError("saved response input changed")
        result = {"video_id": row["video_id"], "input_hash": saved["input_hash"], "original_result_sha256": digest(saved)}
        if not saved.get("raw_response"):
            result.update(status="unavailable", error="no_saved_response")
        else:
            try:
                result.update(evaluate_response(server, saved["raw_response"], video["transcript_text"], video))
            except (ValueError, TypeError, KeyError) as exc:
                result.update(status="validation_failed", error=str(exc)[:500])
        results.append(result)
    fingerprint = digest({name: hashlib.sha256((ROOT / "backend" / name).read_bytes()).hexdigest()
                          for name in ("server.py", "claim_contract.py", "claim_review.py", "claim_wire.py", "claim_safety.py")})
    report = {"validation_fingerprint": fingerprint, "prompt_version": server.PROMPT_VERSION,
              "model_calls": 0, "production_writes": 0, "gate": "not_evaluated", "samples": results,
              "statuses": dict(Counter(row["status"] for row in results)),
              "retained_candidates": sum(len(row.get("claims", [])) for row in results)}
    save_json(workspace / "rechecks" / (fingerprint + ".json"), report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("audit", "sample", "verify", "recheck"))
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=8)
    parser.add_argument("--execute-model-calls", action="store_true")
    parser.add_argument("--selection-from", type=Path, help="repeat exactly these IDs and transcript hashes")
    parser.add_argument("--exclude-from", type=Path, help="exclude a previous sample selection for a holdout")
    args = parser.parse_args()
    os.umask(0o077)
    import server
    if args.action in ("audit", "verify"):
        sys.path.insert(0, str(ROOT / "scripts"))
        from init_db import database_url
    if args.action == "audit":
        if (args.workspace / "snapshot.private.json").exists():
            raise ValueError("workspace already contains an immutable snapshot")
        snapshot = read_database(database_url())
        audit = inventory(snapshot, server.PROMPT_VERSION, server.MIN_TRANSCRIPT_LENGTH)
        save_json(args.workspace / "snapshot.private.json", snapshot)
        save_json(args.workspace / "inventory.json", audit)
        print(json.dumps({key: audit[key] for key in ("prompt_version", "states", "active_claim_versions", "signatures")}, ensure_ascii=False))
    elif args.action == "verify":
        before = json.loads((args.workspace / "inventory.json").read_text())["signatures"]
        after = signatures(read_database(database_url()))
        result = {"checked_at": int(time.time()), "business_data_unchanged": before == after,
                  "before": before, "after": after}
        save_json(args.workspace / "verification.json", result)
        print(json.dumps({"business_data_unchanged": result["business_data_unchanged"]}))
        if before != after:
            raise ValueError("business data changed; inspect concurrent writes before continuing")
    elif args.action == "recheck":
        result = recheck_samples(args.workspace, server)
        print(json.dumps({key: result[key] for key in ("statuses", "retained_candidates", "model_calls", "production_writes", "validation_fingerprint")}))
    elif not args.execute_model_calls:
        raise ValueError("sample requires --execute-model-calls; no database writes are performed")
    else:
        print(json.dumps(stage_sample(args.workspace, server, args.limit, args.selection_from, args.exclude_from), ensure_ascii=False))


if __name__ == "__main__":
    main()
