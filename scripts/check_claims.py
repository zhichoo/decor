#!/usr/bin/env python3
"""Check every stored card without model calls, replacements, or business writes."""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "scripts"))
import claim_safety
from claim_upgrade import read_database, save_json, signatures, text_hash


def code_fingerprint():
    paths = [ROOT / "backend" / name for name in (
        "claim_safety.py", "claim_contract.py", "claim_review.py", "claim_wire.py", "server.py")]
    paths += [Path(__file__).resolve(), ROOT / "scripts/claim_upgrade.py"]
    return hashlib.sha256(json.dumps({str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
                                     for path in paths}, sort_keys=True).encode()).hexdigest()


def content_key(claim):
    return json.dumps({key: claim.get(key) or ([] if key in ("original_reasons", "alternatives") else "未提及")
                       for key in ("object_name", "original_conclusion", "original_reasons", "alternatives",
                                   "conditions", "price_info")}, ensure_ascii=False, sort_keys=True)


def saved_bindings(run, transcript, server, title=""):
    if not run or run.get("input_hash") != text_hash(transcript):
        return {}
    raw = run.get("raw_response_json")
    if not raw:
        return {}
    try:
        payload = server.parse_deepseek_content(raw if isinstance(raw, str) else json.dumps(raw))
        if payload.get("extraction_contract") == server.claim_wire.VERSION:
            payload = server.claim_wire.normalize(payload, transcript, title=title)
        elif payload.get("extraction_contract") in ("v12", "v14", "v16", "v17"):
            payload = server.claim_wire.normalize_historical(payload, transcript, title=title)
        strict = payload.get("extraction_contract") == server.claim_contract.VERSION
        if strict:
            server.claim_contract.validate(payload, transcript, title=title)
        groups = defaultdict(list)
        for claim in payload.get("claims") or []:
            quotes = claim.get("source_quotes") if isinstance(claim, dict) else None
            if (not isinstance(quotes, list) or not quotes
                    or any(not isinstance(quote, str) or len(quote.strip()) < 6 or quote not in transcript for quote in quotes)):
                continue
            candidate = {**claim, "_has_field_bindings": strict}
            groups[content_key(server.claim_contract.attributed(claim) if strict else claim)].append(candidate)
        return {key: values[0] for key, values in groups.items() if len(values) == 1}
    except (ValueError, TypeError, KeyError, AttributeError):
        return {}


def check_snapshot(snapshot, server):
    videos = {video["id"]: video for video in snapshot["videos"]}
    runs = {run["id"]: run for run in snapshot["extraction_runs"]}
    cached_bindings, duplicate_groups = {}, defaultdict(list)
    records = []
    for claim in snapshot["claims"]:
        video = videos.get(claim["video_id"])
        record = {"claim_id": claim["id"], "video_id": claim["video_id"], "object_name": claim.get("object_name"),
                  "findings": [], "warnings": [], "limitations": []}
        records.append(record)
        if claim.get("deleted_at") is not None:
            record["status"] = "archived_deleted_card"
            continue
        if not video or video.get("deleted_at") is not None:
            record["status"] = "archived_deleted_video" if video else "orphan_video"
            continue
        transcript = video.get("transcript_text") or ""
        run = runs.get(claim.get("extraction_run_id"))
        record["prompt_version"] = (run or {}).get("prompt_version", "legacy_unknown")
        record["creator"] = video.get("creator")
        if not run or not run.get("input_hash"):
            record["limitations"].append("missing_extraction_lineage")
        elif run.get("video_id") != claim["video_id"] or not run.get("prompt_version"):
            record["limitations"].append("invalid_extraction_lineage")
        elif run["input_hash"] != text_hash(transcript):
            record["limitations"].append("source_changed_since_extraction")
        if not transcript.strip():
            record["limitations"].append("missing_transcript")
        quotes = claim.get("source_quotes")
        if not isinstance(quotes, list) or not quotes:
            quotes = []
            record["limitations"].append("missing_card_quotes")
        elif any(not isinstance(quote, str) or quote not in transcript for quote in quotes):
            record["findings"].append({"code": "quote_not_in_current_transcript"})
            quotes = [quote for quote in quotes if isinstance(quote, str) and quote in transcript]
        if server.advertising.current_review(video).get("decision") == "advertising":
            record["warnings"].append({"code": "promotional_source_requires_content_check"})
        information_kind = server.claim_review.low_information_kind(claim)
        if information_kind:
            record["warnings"].append({"code": "low_information_claim", "kind": information_kind})
            record["recommended_action"] = (
                "reextract" if information_kind == "bare_evaluation" and not claim.get("source_quotes")
                else "discard_candidate")
        binding, candidate = None, None
        stored = any(claim.get(key) is not None for key in (
            "field_evidence", "source_scope", "scope_quote", "evidence_contract"))
        lineage_matches = (run and run.get("video_id") == claim["video_id"]
                           and run.get("input_hash") == text_hash(transcript) and run.get("prompt_version"))
        if stored:
            try:
                server.claim_contract.validate_stored_evidence(claim, transcript)
                if lineage_matches:
                    binding = claim
                    record["evidence_origin"] = "stored_card_bindings"
                    record["evidence_contract"] = claim["evidence_contract"]
            except (ValueError, TypeError, KeyError) as exc:
                record["findings"].append({"code": "invalid_stored_evidence", "reason": str(exc)})
        elif lineage_matches:
            if run["id"] not in cached_bindings:
                cached_bindings[run["id"]] = saved_bindings(run, transcript, server, video.get("title", ""))
            candidate = cached_bindings[run["id"]].get(content_key(claim))
            if candidate and not quotes:
                quotes = candidate["source_quotes"]
                record["recovered_quote_count"] = len(quotes)
                record["evidence_origin"] = "matching_extraction_run"
            if candidate and candidate["_has_field_bindings"]:
                binding = candidate
        if quotes and not binding:
            record["limitations"].append("missing_field_bindings")
        # Never fabricate per-field bindings for old cards or call a whole-video search proof.
        for field, text in server.claim_contract.field_values(claim).items():
            if binding:
                evidence = " ".join(binding["source_quotes"][ref] for ref in binding["field_evidence"][field])
            else:
                evidence = " ".join(quotes) if quotes else transcript
            errors = claim_safety.numeric_errors(text, evidence, server.numeric_evidence_values)
            if errors:
                target = record["findings"] if binding else record["warnings"]
                target.append({"code": "field_quantity_error" if binding else "unbound_quantity_warning",
                               "field": field, "details": errors})
            subtotal_errors = claim_safety.subtotal_scope_errors(text, evidence, server.numeric_evidence_values)
            if subtotal_errors:
                target = record["findings"] if binding else record["warnings"]
                target.append({"code": "subtotal_scope_error" if binding else "unbound_subtotal_warning",
                               "field": field, "details": subtotal_errors})
        if binding:
            record["findings"] += [{"code": "explicit_condition_not_preserved", **issue}
                                   for issue in claim_safety.condition_issues(binding, transcript, server.numeric_evidence_values)]
            record["findings"] += [{"code": "ambiguous_measurement", **issue}
                                   for issue in server.claim_review.measurement_issues(binding, server.numeric_evidence_values)]
            tradeoffs = claim_safety.tradeoff_issues(binding, transcript, server.numeric_evidence_values)
            target = record["findings"] if binding.get("evidence_spans") else record["warnings"]
            target.extend({"code": "explicit_tradeoff_not_preserved" if binding.get("evidence_spans")
                           else "local_tradeoff_warning", **issue} for issue in tradeoffs)
        else:
            record["limitations"].append("condition_coverage_not_verifiable")
            if quotes:
                unbound = {**claim, "source_quotes": quotes, "field_evidence": {}}
                record["warnings"] += [{"code": "potential_condition_loss", **issue}
                                       for issue in claim_safety.condition_issues(unbound, transcript, server.numeric_evidence_values)]
        record["status"] = ("issues_detected" if record["findings"] else
                            "insufficient_evidence" if record["limitations"] else "no_rule_findings")
        duplicate_groups[content_key(claim)].append(claim["id"])
    active = [record for record in records if record["status"] in (
        "issues_detected", "insufficient_evidence", "no_rule_findings")]
    summary = {
        "prompt_version": server.PROMPT_VERSION, "total_rows_checked": len(records), "active_cards_checked": len(active),
        "statuses": dict(Counter(record["status"] for record in records)),
        "finding_cards": dict(Counter(code for record in active for code in {item["code"] for item in record["findings"]})),
        "warning_cards": dict(Counter(code for record in active for code in {item["code"] for item in record["warnings"]})),
        "limitation_cards": dict(Counter(code for record in active for code in set(record["limitations"]))),
        "cards_with_warnings": sum(bool(record["warnings"]) for record in active),
        "cards_with_recovered_quotes": sum(bool(record.get("recovered_quote_count")) for record in active),
        "model_calls": 0, "production_writes": 0,
        "meaning": "No rule finding is not semantic or factual verification. Missing evidence is never a pass.",
    }
    return {"summary": summary, "cards": records,
            "exact_content_duplicate_groups": [ids for ids in duplicate_groups.values() if len(ids) > 1]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    args = parser.parse_args()
    os.umask(0o077)
    if args.workspace.exists():
        raise ValueError("use a fresh audit workspace")
    import server
    from init_db import database_url
    fingerprint = code_fingerprint()
    snapshot = read_database(database_url())
    save_json(args.workspace / "snapshot.private.json", snapshot)
    report = check_snapshot(snapshot, server)
    report["before"] = signatures(snapshot)
    if code_fingerprint() != fingerprint:
        raise ValueError("checker code changed during audit; use a fresh workspace")
    report["validation_fingerprint"] = fingerprint
    save_json(args.workspace / "report.private.json", report)
    after = signatures(read_database(database_url()))
    unchanged = report["before"] == after
    save_json(args.workspace / "verification.json", {"business_data_unchanged": unchanged,
                                                    "before": report["before"], "after": after})
    print(json.dumps(report["summary"] | {"business_data_unchanged": unchanged}, ensure_ascii=False))
    if not unchanged:
        raise ValueError("business data changed during audit; inspect before using this report")


if __name__ == "__main__":
    main()
