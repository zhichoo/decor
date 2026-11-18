#!/usr/bin/env python3
"""Explicitly apply selected saved trials; never call a model or restore deleted content."""
import argparse
import json
import os
from pathlib import Path

import claim_upgrade as upgrade


def apply_sample(conn, server, saved, snapshot, *, execute=False):
    video_id = saved["video_id"]
    expected = next((v for v in snapshot["videos"] if v["id"] == video_id), None)
    if not expected or saved.get("status") not in upgrade.SUCCESS:
        raise ValueError("sample_not_successful")
    if saved.get("prompt_version") != server.PROMPT_VERSION or saved.get("model") != server.active_model_name():
        raise ValueError("sample_version_changed")
    expected_cards = sorted((c for c in snapshot["claims"]
                             if c["video_id"] == video_id and c.get("deleted_at") is None), key=lambda c: c["id"])
    with server.video_process_lock(video_id), conn.transaction():
        row = conn.execute("SELECT * FROM videos WHERE id=%s FOR UPDATE", (video_id,)).fetchone()
        if not row or row.get("deleted_at") is not None:
            raise ValueError("video_deleted_or_missing")
        current = server.row_to_video(row)
        input_hash = upgrade.text_hash(current.get("transcript_text"))
        if saved.get("input_hash") != input_hash or upgrade.text_hash(expected.get("transcript_text")) != input_hash:
            raise ValueError("sample_input_changed")
        if server.advertising.current_review(current).get("decision") != "not_ad":
            raise ValueError("sample_advertising_or_unresolved")
        prompt = server.build_extract_prompt(current)
        if saved.get("fingerprint") != upgrade.digest([server.PROMPT_VERSION, server.active_model_name(), prompt]):
            raise ValueError("sample_prompt_changed")
        cards = conn.execute("SELECT * FROM claims WHERE video_id=%s ORDER BY id FOR UPDATE", (video_id,)).fetchall()
        if any(upgrade.deletion_guard(card) for card in cards):
            raise ValueError("manual_deletion_guard")
        active = [card for card in cards if card.get("deleted_at") is None]
        previous = conn.execute("""SELECT id, status FROM extraction_runs
            WHERE video_id=%s AND input_hash=%s AND prompt_version=%s AND status IN ('completed','filtered')
            ORDER BY created_at DESC, id DESC LIMIT 1""", (video_id, input_hash, server.PROMPT_VERSION)).fetchone()
        if previous and ((not active and previous["status"] == "filtered") or
                         (active and all(c.get("extraction_run_id") == previous["id"]
                                         and upgrade.has_stored_evidence(c, current["transcript_text"]) for c in active))):
            return {"video_id": video_id, "status": "skipped_current", "new_claims": len(active)}
        # Nullable migration columns must not make the old snapshot look changed.
        projected = [{key: card.get(key) for key in expected_cards[0]} for card in active] if expected_cards else active
        if upgrade.digest(projected) != upgrade.digest(expected_cards):
            raise ValueError("sample_old_cards_changed")
        evaluated = upgrade.evaluate_response(server, saved.get("raw_response"), current["transcript_text"], current)
        result = {"video_id": video_id, "status": "ready" if not execute else evaluated["status"],
                  "old_claims": len(active), "new_claims": len(evaluated["claims"]),
                  "excluded_items": len(evaluated["excluded"])}
        if not execute:
            return result
        run_id = server.new_id("run")
        conn.execute("""INSERT INTO extraction_runs (id, video_id, model, prompt_version, input_hash,
            prompt_text, raw_response_json, status, error_message, review_data, created_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,NULL,%s,%s)""",
            (run_id, video_id, saved["model"], saved["prompt_version"], input_hash, prompt,
             server.raw_response_jsonb(saved["raw_response"]), evaluated["status"],
             server.Json({"items": evaluated["excluded"], "superseded": False,
                          "saved_trial_sha256": upgrade.digest(saved)}), saved["created_at"]))
        conn.execute("""UPDATE extraction_runs SET review_data=jsonb_set(review_data,'{superseded}','true')
            WHERE video_id=%s AND id<>%s AND review_data IS NOT NULL""", (video_id, run_id))
        inserted = server.insert_claims(conn, current, run_id, evaluated["claims"])
        conn.execute("UPDATE videos SET status=%s, last_error=NULL, updated_at=%s WHERE id=%s",
                     ("claims_extracted" if inserted else "claims_filtered", server.now(), video_id))
        return result | {"run_id": run_id}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--video-id", action="append", required=True)
    parser.add_argument("--execute-database-writes", action="store_true")
    args = parser.parse_args()
    os.umask(0o077)
    import server
    snapshot = json.loads((args.workspace / "snapshot.private.json").read_text())
    results = []
    for video_id in dict.fromkeys(args.video_id):
        # Resolve IDs from the snapshot, not an arbitrary user-supplied file path.
        if not any(v["id"] == video_id for v in snapshot["videos"]):
            raise ValueError("unknown_sample_video")
        saved = json.loads((args.workspace / "samples" / (video_id + ".json")).read_text())
        if saved.get("video_id") != video_id:
            raise ValueError("sample_video_mismatch")
        with server.connect() as conn:
            result = apply_sample(conn, server, saved, snapshot, execute=args.execute_database_writes)
        results.append(result)
        print(json.dumps(result, ensure_ascii=False), flush=True)
    upgrade.save_json(args.workspace / ("applied.private.json" if args.execute_database_writes else "apply-plan.private.json"),
                      {"model_calls": 0, "execute": args.execute_database_writes, "results": results})


if __name__ == "__main__":
    main()
