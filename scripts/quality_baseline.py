#!/usr/bin/env python3
"""Freeze read-only quality samples, validate human labels, and report without model calls."""
import argparse
from collections import Counter
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sys
from urllib.parse import urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from claim_review import rule_issues

VERSION = 1
TOOL_VERSION = "quality_baseline_v1"
CLAIM_FIELDS = (
    "id", "video_id", "extraction_run_id", "object_name", "stance", "author_stance",
    "content_type", "process_stage", "original_conclusion", "conditions", "price_info",
    "source_quotes", "space_tags", "topic_tags", "original_reasons", "alternatives", "created_at",
)
VIDEO_FIELDS = (
    "id", "source_id", "platform", "creator", "title", "source_url", "published_at",
    "transcript_text", "transcript_source", "transcript_created_at", "status", "created_at", "updated_at",
)
RUN_FIELDS = ("id", "video_id", "model", "prompt_version", "input_hash", "status", "created_at")
LIST_FIELDS = ("source_quotes", "space_tags", "topic_tags", "original_reasons", "alternatives")
ERROR_TYPES = frozenset((
    "transcription", "parameter", "object", "attitude", "scope", "unsupported",
    "evidence", "advertising", "wording",
))
SEVERITIES = frozenset(("severe", "moderate", "minor"))
METHODS = frozenset(("transcript", "original_video", "both", "unavailable"))
GROUPS = ("random", "challenge", "whole_video")
RISK_PATTERNS = {
    "numeric": r"[0-9零一二三四五六七八九十百千万]+\s*(?:毫米|厘米|公分|米|元|块|万|mm|cm|m\b|%)",
    "safety": r"承重|结构|燃气|漏电|电线|接地|防火|防水",
    "negation": r"不要|不能|不建议|不推荐|千万别|别做",
    "price": r"价格|报价|预算|费用|单价|元|块钱",
}


class QualityError(ValueError):
    """A safe, tool-authored validation message without user data or credentials."""


def require(condition, message):
    if not condition:
        raise QualityError(message)


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def now():
    return datetime.now(timezone.utc).isoformat()


def strict_object(value, fields, label):
    require(isinstance(value, dict) and set(value) == set(fields), f"invalid {label} fields")


def nonempty(value):
    return isinstance(value, str) and bool(value.strip())


def keyed(rows, label):
    require(isinstance(rows, list), f"{label} must be a list")
    result = {}
    for row in rows:
        require(isinstance(row, dict) and nonempty(row.get("id")), f"invalid {label} ID")
        require(row["id"] not in result, f"duplicate {label} ID")
        result[row["id"]] = row
    return result


def project(row, fields):
    return {field: row.get(field) for field in fields}


def source_url(value):
    try:
        parts = urlsplit(value or "")
        if parts.scheme not in ("http", "https") or not parts.hostname or parts.username or parts.password:
            return ""
        return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
    except (TypeError, ValueError):
        return ""


def normalize_snapshot(raw):
    """Allowlist inputs before freezing: no configuration, jobs, raw responses, or review notes."""
    require(isinstance(raw, dict), "snapshot must be an object")
    all_videos = keyed(raw.get("videos"), "video")
    all_claims = keyed(raw.get("claims"), "claim")
    all_runs = keyed(raw.get("runs", []), "run")
    videos = {}
    for key, row in all_videos.items():
        if row.get("deleted_at") is not None:
            continue
        video = project(row, VIDEO_FIELDS)
        video["source_url"] = source_url(video["source_url"])
        for field in ("title", "transcript_text", "creator", "platform"):
            video[field] = video[field] or ""
            require(isinstance(video[field], str), f"invalid video {field}")
        # Keep only public review decisions, never private review reasons or evidence.
        if "ad_review" in row or "ad_review_override" in row:
            from advertising import current_review
            video["ad_decision"] = current_review(row).get("decision")
        else:
            decision = row.get("ad_decision")
            require(decision in (None, "advertising", "not_ad", "uncertain", "error"), "invalid ad decision")
            video["ad_decision"] = decision
        videos[key] = video
    claims = {}
    for key, row in all_claims.items():
        if row.get("deleted_at") is not None:
            continue
        require(row.get("video_id") in all_videos, "claim references missing video")
        if row["video_id"] not in videos:
            continue
        claim = project(row, CLAIM_FIELDS)
        for field in LIST_FIELDS:
            claim[field] = claim[field] or []
            require(isinstance(claim[field], list) and all(isinstance(x, str) for x in claim[field]),
                    f"invalid claim {field}")
        for field in ("object_name", "original_conclusion", "conditions", "price_info"):
            claim[field] = claim[field] or ""
            require(isinstance(claim[field], str), f"invalid claim {field}")
        claims[key] = claim
    run_ids = {c["extraction_run_id"] for c in claims.values() if c["extraction_run_id"]}
    runs = {}
    for key in sorted(run_ids):
        if key not in all_runs:
            continue  # Legacy exports may not include run metadata; absence stays explicit.
        row = all_runs[key]
        require(row.get("video_id") in videos, "run references missing or deleted video")
        runs[key] = project(row, RUN_FIELDS)
    for claim in claims.values():
        run = runs.get(claim["extraction_run_id"])
        require(run is None or run["video_id"] == claim["video_id"], "claim/run video mismatch")
    return {"videos": sorted(videos.values(), key=lambda r: r["id"]),
            "claims": sorted(claims.values(), key=lambda r: r["id"]),
            "runs": sorted(runs.values(), key=lambda r: r["id"])}


def read_database(dsn):
    """No server import/startup/migrations; one read-only repeatable-read transaction."""
    import psycopg2
    from psycopg2.extras import RealDictCursor

    require(nonempty(dsn), "database URL environment variable is empty")
    with closing(psycopg2.connect(dsn, cursor_factory=RealDictCursor, connect_timeout=10)) as conn:
        conn.set_session(readonly=True, isolation_level="REPEATABLE READ")
        with conn.cursor() as cur:
            cur.execute("SET LOCAL statement_timeout = '30s'")
            cur.execute("SELECT " + ", ".join("v." + f for f in VIDEO_FIELDS) +
                        ", to_jsonb(v)->'ad_review' AS ad_review, "
                        "to_jsonb(v)->'ad_review_override' AS ad_review_override "
                        "FROM public.videos v WHERE v.deleted_at IS NULL ORDER BY v.id")
            videos = [dict(row) for row in cur.fetchall()]
            optional = {"author_stance", "content_type", "source_quotes"}
            fields = [(f"to_jsonb(c)->'{f}' AS {f}" if f in optional else "c." + f) for f in CLAIM_FIELDS]
            cur.execute("SELECT " + ", ".join(fields) + " FROM public.claims c "
                        "JOIN public.videos v ON v.id=c.video_id "
                        "WHERE c.deleted_at IS NULL AND v.deleted_at IS NULL ORDER BY c.id")
            claims = [dict(row) for row in cur.fetchall()]
            cur.execute("SELECT " + ", ".join("r." + f for f in RUN_FIELDS) +
                        " FROM public.extraction_runs r WHERE EXISTS "
                        "(SELECT 1 FROM public.claims c JOIN public.videos v ON v.id=c.video_id "
                        "WHERE c.extraction_run_id=r.id AND c.deleted_at IS NULL AND v.deleted_at IS NULL) "
                        "ORDER BY r.id")
            runs = [dict(row) for row in cur.fetchall()]
    return {"videos": videos, "claims": claims, "runs": runs}


def risk_signals(claim, video):
    text = " ".join([claim["object_name"], claim["original_conclusion"], claim["conditions"],
                     claim["price_info"], *claim["source_quotes"]])
    signals = {name for name, pattern in RISK_PATTERNS.items() if re.search(pattern, text)}
    if not claim["source_quotes"]:
        signals.add("missing_quotes")
    elif any(not quote.strip() or quote not in video["transcript_text"] for quote in claim["source_quotes"]):
        signals.add("quote_mismatch")
    signals.update("rule_" + item["type"] for item in rule_issues(claim))
    if video["ad_decision"] in ("advertising", "uncertain", "error"):
        signals.add("advertising_context")
    return sorted(signals)


def ranked(ids, seed, group, count):
    return sorted(ids, key=lambda key: (digest([seed, group, key]), key))[:count]


def sample_hash(sample, snapshot):
    videos = {r["id"]: r for r in snapshot["videos"]}
    claims = {r["id"]: r for r in snapshot["claims"]}
    runs = {r["id"]: r for r in snapshot["runs"]}
    if sample["kind"] == "claim":
        claim = claims[sample["record_id"]]
        return digest({"claim": claim, "video": videos[claim["video_id"]],
                       "run": runs.get(claim["extraction_run_id"])})
    video = videos[sample["record_id"]]
    related = [c for c in snapshot["claims"] if c["video_id"] == video["id"]]
    return digest({"video": video, "claims": related,
                   "runs": [runs[key] for key in sorted({c["extraction_run_id"] for c in related
                                                       if c["extraction_run_id"] in runs})]})


def select_samples(snapshot, signals, seed, counts):
    videos = {r["id"]: r for r in snapshot["videos"]}
    claims = {r["id"]: r for r in snapshot["claims"]}
    pools = {"random": list(claims), "challenge": [key for key in claims if signals[key]],
             "whole_video": [key for key in videos if videos[key]["transcript_text"].strip()
                             and videos[key]["transcript_text"].strip() != videos[key]["title"].strip()]}
    selected = {group: ranked(pools[group], seed, group, counts[group]) for group in GROUPS}
    samples = {}
    for group in GROUPS:
        kind = "video" if group == "whole_video" else "claim"
        for key in selected[group]:
            sample_id = kind + ":" + key
            item = samples.setdefault(sample_id, {"sample_id": sample_id, "kind": kind,
                "record_id": key, "groups": [], "signals": signals[key] if kind == "claim" else []})
            item["groups"].append(group)
    for sample in samples.values():
        sample["snapshot_hash"] = sample_hash(sample, snapshot)
    return (sorted(samples.values(), key=lambda s: s["sample_id"]),
            {g: len(pools[g]) for g in GROUPS}, {g: len(selected[g]) for g in GROUPS})


def freeze(raw, seed=20261029, random_count=100, challenge_count=20, video_count=5, created_at=None):
    for value in (seed, random_count, challenge_count, video_count):
        require(type(value) is int, "seed and counts must be integers")
    require(min(random_count, challenge_count, video_count) >= 0, "sample counts cannot be negative")
    snapshot = normalize_snapshot(raw)
    videos = {r["id"]: r for r in snapshot["videos"]}
    signals = {c["id"]: risk_signals(c, videos[c["video_id"]]) for c in snapshot["claims"]}
    counts = dict(zip(GROUPS, (random_count, challenge_count, video_count)))
    samples, eligible, selected = select_samples(snapshot, signals, seed, counts)
    rule_path = ROOT / "backend" / "claim_review.py"
    dataset = {"format_version": VERSION, "tool_version": TOOL_VERSION, "created_at": created_at or now(),
               "provenance": {"tool_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                              "rule_sha256": hashlib.sha256(rule_path.read_bytes()).hexdigest()},
               "sampling": {"seed": seed, "algorithm": "sha256_rank_v1", "requested": counts,
                            "eligible": eligible, "selected": selected, "risk_signals": signals},
               "snapshot": snapshot, "samples": samples}
    dataset["dataset_id"] = digest(dataset)
    return dataset


def validate_dataset(dataset):
    strict_object(dataset, ("format_version", "tool_version", "created_at", "provenance", "sampling", "snapshot",
                            "samples", "dataset_id"), "dataset")
    require(dataset["format_version"] == VERSION and dataset["tool_version"] == TOOL_VERSION,
            "unsupported dataset version")
    require(dataset["dataset_id"] == digest({k: v for k, v in dataset.items() if k != "dataset_id"}),
            "dataset integrity mismatch")
    settings = dataset["sampling"]
    strict_object(settings, ("seed", "algorithm", "requested", "eligible", "selected", "risk_signals"), "sampling")
    require(isinstance(settings.get("requested"), dict), "invalid sampling counts")
    require(set(settings["requested"]) == set(GROUPS), "invalid sample groups")
    require(type(settings["seed"]) is int and settings["algorithm"] == "sha256_rank_v1", "invalid sampling algorithm")
    require(all(type(c) is int and c >= 0 for c in settings["requested"].values()), "invalid sample counts")
    strict_object(dataset["provenance"], ("tool_sha256", "rule_sha256"), "provenance")
    require(all(isinstance(v, str) and re.fullmatch(r"[a-f0-9]{64}", v)
                for v in dataset["provenance"].values()), "invalid implementation hashes")
    require(dataset["snapshot"] == normalize_snapshot(dataset["snapshot"]), "snapshot contains non-canonical or private data")
    signals = settings["risk_signals"]
    require(isinstance(signals, dict) and set(signals) == {c["id"] for c in dataset["snapshot"]["claims"]},
            "invalid frozen signal IDs")
    require(all(isinstance(items, list) and all(nonempty(x) for x in items)
                and items == sorted(set(items)) for items in signals.values()), "invalid frozen signals")
    # Replay stored signals, not today's heuristics: upgrading rules must not invalidate human labels.
    samples, eligible, selected = select_samples(dataset["snapshot"], signals, settings["seed"], settings["requested"])
    require(dataset["samples"] == samples and settings["eligible"] == eligible and settings["selected"] == selected,
            "dataset sampling or snapshot mismatch")
    return dataset


def annotation_template(dataset):
    validate_dataset(dataset)
    return {"format_version": VERSION, "dataset_id": dataset["dataset_id"], "entries": [
        {"sample_id": sample["sample_id"], "snapshot_hash": sample["snapshot_hash"],
         "verdict": "pending", "review_method": None, "reviewer": "", "reviewed_at": None,
         "review_seconds": None, "notes": "", "errors": [], "reference_claims": []}
        for sample in dataset["samples"]]}


def check_evidence(item, video, claim, method):
    require(nonempty(item["evidence"]), "evidence cannot be empty")
    source = item["evidence_source"]
    require(source in ("transcript", "claim", "original_video", "title"), "invalid evidence source")
    if source == "original_video":
        require(method in ("original_video", "both"), "original-video evidence requires video review")
        return
    if source == "claim":
        require(claim is not None, "claim evidence is only valid for a claim sample")
        fields = ("object_name", "original_conclusion", "conditions", "price_info", "stance",
                  "author_stance", "content_type", "process_stage")
        texts = [claim[field] for field in fields if isinstance(claim[field], str)]
        texts.extend(text for field in LIST_FIELDS for text in claim[field])
    else:
        texts = [video["transcript_text"] if source == "transcript" else video["title"]]
    require(any(item["evidence"] in text for text in texts), "evidence must be an exact source excerpt")


def validate_annotations(dataset, annotations):
    validate_dataset(dataset)
    strict_object(annotations, ("format_version", "dataset_id", "entries"), "annotation document")
    require(annotations["format_version"] == VERSION, "unsupported annotation version")
    require(annotations["dataset_id"] == dataset["dataset_id"], "annotations belong to another dataset")
    require(isinstance(annotations["entries"], list), "annotation entries must be a list")
    samples = {s["sample_id"]: s for s in dataset["samples"]}
    snapshot = dataset["snapshot"]
    claims = {c["id"]: c for c in snapshot["claims"]}
    videos = {v["id"]: v for v in snapshot["videos"]}
    seen = set()
    for entry in annotations["entries"]:
        strict_object(entry, ("sample_id", "snapshot_hash", "verdict", "review_method", "reviewer",
                             "reviewed_at", "review_seconds", "notes", "errors", "reference_claims"), "annotation")
        key = entry["sample_id"]
        require(isinstance(key, str) and key in samples and key not in seen, "unknown or duplicate sample ID")
        seen.add(key)
        sample = samples[key]
        require(entry["snapshot_hash"] == sample["snapshot_hash"], "annotation snapshot mismatch")
        verdict = entry["verdict"]
        require(verdict in ("pending", "pass", "fail", "unable"), "invalid verdict")
        require(isinstance(entry["notes"], str) and isinstance(entry["reviewer"], str), "invalid notes/reviewer")
        require(isinstance(entry["errors"], list) and isinstance(entry["reference_claims"], list), "invalid labels")
        if verdict == "pending":
            require(not entry["errors"] and not entry["reference_claims"] and entry["review_method"] is None
                    and entry["reviewed_at"] is None and entry["review_seconds"] is None,
                    "pending entries cannot contain completed labels")
            continue
        method = entry["review_method"]
        require(method in METHODS and nonempty(entry["reviewer"]), "completed labels need reviewer and method")
        require(nonempty(entry["reviewed_at"]), "completed labels need a review timestamp")
        try:
            stamp = datetime.fromisoformat(entry["reviewed_at"].replace("Z", "+00:00"))
            require(stamp.utcoffset() is not None, "review timestamp must include timezone")
        except (TypeError, ValueError):
            raise QualityError("invalid review timestamp") from None
        seconds = entry["review_seconds"]
        require(type(seconds) in (int, float) and math.isfinite(seconds) and seconds >= 0,
                "review seconds must be a finite nonnegative number")
        if verdict == "unable":
            require(nonempty(entry["notes"]) and not entry["errors"] and not entry["reference_claims"],
                    "unable entries need a reason, not correctness labels")
            continue
        require(method != "unavailable", "unavailable evidence cannot establish pass/fail")
        claim = claims[sample["record_id"]] if sample["kind"] == "claim" else None
        video = videos[claim["video_id"] if claim else sample["record_id"]]
        error_keys = set()
        for error in entry["errors"]:
            strict_object(error, ("type", "severity", "evidence", "evidence_source", "note"), "error")
            require(error["type"] in ERROR_TYPES and error["severity"] in SEVERITIES, "invalid error category/severity")
            require(nonempty(error["note"]), "error needs an explanation")
            check_evidence(error, video, claim, method)
            error_key = (error["type"], error["evidence_source"], error["evidence"])
            require(error_key not in error_keys, "duplicate error annotation")
            error_keys.add(error_key)
        references = entry["reference_claims"]
        require(claim is None or not references, "claim samples cannot label whole-video omissions")
        if claim is None:
            require(method in ("original_video", "both"), "whole-video judgments require reviewing the original video")
        reference_texts = set()
        for reference in references:
            strict_object(reference, ("text", "evidence", "evidence_source", "disposition", "matched_claim_ids", "reason"),
                          "reference claim")
            require(nonempty(reference["text"]) and reference["text"].strip() not in reference_texts,
                    "empty or duplicate reference claim")
            reference_texts.add(reference["text"].strip())
            check_evidence(reference, video, None, method)
            disposition = reference["disposition"]
            require(disposition in ("covered", "omitted", "excluded"), "invalid reference disposition")
            matched = reference["matched_claim_ids"]
            require(isinstance(matched, list) and all(isinstance(x, str) for x in matched)
                    and len(set(matched)) == len(matched), "invalid matched claim IDs")
            require(all(x in claims and claims[x]["video_id"] == video["id"] for x in matched),
                    "reference matched a claim from another video")
            require(bool(matched) == (disposition == "covered"), "only covered references need matched claim IDs")
            require(isinstance(reference["reason"], str), "invalid reference reason")
            require(disposition == "covered" or nonempty(reference["reason"]), "omitted/excluded references need a reason")
        omitted = sum(r["disposition"] == "omitted" for r in references)
        has_error = bool(entry["errors"] or omitted)
        require((verdict == "fail") == has_error, "verdict contradicts error/omission labels")
        if claim is None and not references:
            require(nonempty(entry["notes"]), "whole-video review with no reference claims needs an explanation")
    require(seen == set(samples), "missing sample entries; keep unfinished entries pending")
    return annotations


def rate(numerator, denominator):
    return {"numerator": numerator, "denominator": denominator,
            "rate": numerator / denominator if denominator else None}


def report(dataset, annotations):
    validate_annotations(dataset, annotations)
    labels = {r["sample_id"]: r for r in annotations["entries"]}
    snapshot = dataset["snapshot"]
    videos = {v["id"]: v for v in snapshot["videos"]}
    claims = {c["id"]: c for c in snapshot["claims"]}
    groups = {}
    for group in GROUPS:
        samples = [s for s in dataset["samples"] if group in s["groups"]]
        entries = [labels[s["sample_id"]] for s in samples]
        judged = [e for e in entries if e["verdict"] in ("pass", "fail")]
        errors = [error for entry in judged for error in entry["errors"]]
        counts = Counter(e["verdict"] for e in entries)
        # Count affected units as well as occurrences: multiple errors can occur on one card.
        by_type = {kind: sum(any(e["type"] == kind for e in row["errors"]) for row in judged)
                   for kind in sorted(ERROR_TYPES)}
        distribution = Counter()
        for sample in samples:
            video = videos[claims[sample["record_id"]]["video_id"] if sample["kind"] == "claim"
                           else sample["record_id"]]
            distribution[(video["platform"], video["creator"])] += 1
        durations = sorted(e["review_seconds"] for e in entries if e["verdict"] != "pending")
        midpoint = len(durations) // 2
        median = ((durations[midpoint - 1] + durations[midpoint]) / 2 if len(durations) % 2 == 0
                  else durations[midpoint]) if durations else None
        groups[group] = {
            "selected": len(samples), "verdicts": {v: counts[v] for v in ("pending", "pass", "fail", "unable")},
            "failed_units": rate(counts["fail"], len(judged)),
            "units_by_error_type": by_type, "error_occurrences": len(errors),
            "occurrences_by_severity": dict(Counter(e["severity"] for e in errors)),
            "review_seconds": {"total": sum(durations), "median": median},
            "review_methods": dict(Counter(e["review_method"] for e in entries if e["verdict"] != "pending")),
            "distribution": [{"platform": k[0], "creator": k[1], "units": value}
                             for k, value in sorted(distribution.items())],
        }
        if group != "whole_video":
            judged_samples = [s for s in samples if labels[s["sample_id"]]["verdict"] in ("pass", "fail")]
            flagged = [s for s in judged_samples if s["signals"]]
            failed = [s for s in judged_samples if labels[s["sample_id"]]["verdict"] == "fail"]
            groups[group]["sampling_signal_overlap"] = {
                "flagged_judged": len(flagged),
                "flagged_with_errors": sum(labels[s["sample_id"]]["verdict"] == "fail" for s in flagged),
                "judged_with_errors": len(failed), "errors_with_any_signal": sum(bool(s["signals"]) for s in failed),
                "warning": "Sampling signals are triage hints, not production detector accuracy or error-type recall.",
            }
        else:
            references = [r for entry in judged for r in entry["reference_claims"]]
            reference_counts = Counter(r["disposition"] for r in references)
            groups[group]["omissions"] = rate(reference_counts["omitted"],
                                              reference_counts["covered"] + reference_counts["omitted"])
            groups[group]["reference_claims"] = {key: reference_counts[key] for key in ("covered", "omitted", "excluded")}
    return {
        "format_version": VERSION, "dataset_id": dataset["dataset_id"], "tool_version": TOOL_VERSION,
        "generated_at": now(), "sampling": {k: v for k, v in dataset["sampling"].items() if k != "risk_signals"},
        "provenance": dataset["provenance"], "groups": groups,
        "input_provenance": {
            "snapshot_sha256": digest(snapshot),
            "run_versions": [{"model": key[0], "prompt_version": key[1], "runs": count}
                             for key, count in sorted(Counter((r.get("model") or "", r.get("prompt_version") or "")
                                                              for r in snapshot["runs"]).items())],
            "claims_missing_run_metadata": sum(c["extraction_run_id"] not in {r["id"] for r in snapshot["runs"]}
                                               for c in snapshot["claims"]),
        },
        "underfilled_groups": [g for g in GROUPS if dataset["sampling"]["selected"][g]
                               < dataset["sampling"]["requested"][g]],
        "unique_samples": len(dataset["samples"]),
        "overlap_claims": sum("random" in s["groups"] and "challenge" in s["groups"] for s in dataset["samples"]),
        "unresolved": [{"sample_id": e["sample_id"], "verdict": e["verdict"], "notes": e["notes"]}
                       for e in annotations["entries"] if e["verdict"] in ("pending", "unable")],
        "limits": ["Random, challenge, and whole-video groups must not be pooled into one quality score.",
                   "Pending and unable labels are not passes; a zero denominator has no estimated rate.",
                   "Human source-fidelity labels do not establish factual correctness.",
                   "No model was called; no extraction comparison or independent holdout evaluation was performed."],
    }


def markdown_report(result):
    lines = ["# Quality baseline report", "", f"Dataset: `{result['dataset_id']}`", "",
             "Requested / eligible / selected: " + canonical(result["sampling"]), "",
             "Underfilled groups: " + canonical(result["underfilled_groups"]), "",
             "| Group | Selected | Judged | Failed | Pending | Unable |", "| --- | ---: | ---: | ---: | ---: | ---: |"]
    for group, value in result["groups"].items():
        counts = value["verdicts"]
        lines.append(f"| {group} | {value['selected']} | {counts['pass'] + counts['fail']} | "
                     f"{counts['fail']} | {counts['pending']} | {counts['unable']} |")
    for group, value in result["groups"].items():
        lines.extend(["", "## " + group, "", "Affected units by error type: " + canonical(value["units_by_error_type"]),
                      "", "Error severity occurrences: " + canonical(value["occurrences_by_severity"]),
                      "", "Review seconds: " + canonical(value["review_seconds"])])
        if group == "whole_video":
            lines.extend(["", "Omissions (omitted / covered + omitted): " + canonical(value["omissions"])])
    lines.extend(["", "## Limits", "", *("- " + text for text in result["limits"]), "",
                  "## Unresolved", "", *("- " + item["sample_id"] + " (" + item["verdict"] + ")"
                                         for item in result["unresolved"]), ""])
    return "\n".join(lines)


def inventory(dataset, queries):
    """Literal topic discovery only: matches are candidates, not verified recommendations."""
    validate_dataset(dataset)
    require(isinstance(queries, list) and all(nonempty(q) for q in queries), "queries must be nonempty strings")
    queries = list(dict.fromkeys(q.strip() for q in queries))
    videos = {v["id"]: v for v in dataset["snapshot"]["videos"]}
    claims = dataset["snapshot"]["claims"]
    topics = []
    for query in queries:
        matched = [c for c in claims if query.casefold() in " ".join([
            c["object_name"], c["original_conclusion"], c["conditions"],
            *c["space_tags"], *c["topic_tags"],
        ]).casefold()]
        video_ids = sorted({c["video_id"] for c in matched})
        topics.append({
            "query": query, "claim_count": len(matched), "video_count": len(video_ids),
            "creator_groups": len({(videos[key]["platform"], videos[key]["creator"]) for key in video_ids}),
            "claims_with_quotes": sum(bool(c["source_quotes"]) for c in matched),
            "claim_ids": [c["id"] for c in matched], "video_ids": video_ids,
        })
    return {
        "format_version": VERSION, "dataset_id": dataset["dataset_id"],
        "totals": {"videos": len(videos), "claims": len(claims),
                   "claims_with_quotes": sum(bool(c["source_quotes"]) for c in claims)},
        "object_names": [{"name": key, "claims": value}
                         for key, value in sorted(Counter(c["object_name"] for c in claims).items(),
                                                  key=lambda item: (-item[1], item[0]))],
        "topics": topics,
        "limits": ["Literal keyword candidates only; no clustering, manual review, or fact checking.",
                   "Creator groups are not independently verified sources.",
                   "Quote presence does not establish quote accuracy or source fidelity."],
    }


def load_json(path):
    def reject_constant(value):
        raise ValueError("non-finite JSON number")

    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, "duplicate JSON object key")
            result[key] = value
        return result

    return json.loads(Path(path).read_text(encoding="utf-8"), parse_constant=reject_constant,
                      object_pairs_hook=unique_object)


def write_new(path, value):
    """Exclusive creation: never replace an existing dataset or human annotation file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        stream.write(text)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    sample = commands.add_parser("freeze", help="Freeze allowlisted inputs; no writes to the database")
    source = sample.add_mutually_exclusive_group(required=True)
    source.add_argument("--input", type=Path, help="Private JSON containing videos, claims and optional runs")
    source.add_argument("--database", action="store_true", help="Explicit opt-in to read a database")
    sample.add_argument("--database-env", default="DATABASE_URL", help="Environment variable holding the DSN; no local-config fallback")
    sample.add_argument("--seed", type=int, default=20261029)
    sample.add_argument("--random-count", type=int, default=100)
    sample.add_argument("--challenge-count", type=int, default=20)
    sample.add_argument("--video-count", type=int, default=5)
    sample.add_argument("--output", type=Path, required=True)
    template = commands.add_parser("template", help="Create a pending-only human annotation document")
    template.add_argument("--dataset", type=Path, required=True)
    template.add_argument("--output", type=Path, required=True)
    check = commands.add_parser("validate", help="Validate snapshot identity and human labels")
    check.add_argument("--dataset", type=Path, required=True)
    check.add_argument("--annotations", type=Path, required=True)
    summary = commands.add_parser("report", help="Generate separate group metrics; pending labels are never passes")
    summary.add_argument("--dataset", type=Path, required=True)
    summary.add_argument("--annotations", type=Path, required=True)
    summary.add_argument("--output", type=Path, required=True)
    summary.add_argument("--markdown", type=Path)
    discover = commands.add_parser("inventory", help="Inspect frozen topic coverage without model calls")
    discover.add_argument("--dataset", type=Path, required=True)
    discover.add_argument("--query", action="append", default=[], help="Literal candidate topic; may be repeated")
    discover.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "freeze":
            raw = read_database(os.environ.get(args.database_env, "")) if args.database else load_json(args.input)
            dataset = freeze(raw, args.seed, args.random_count, args.challenge_count, args.video_count)
            write_new(args.output, dataset)
            print("Frozen private dataset: " + dataset["dataset_id"])
            print("Selected: " + canonical(dataset["sampling"]["selected"]))
        elif args.command == "template":
            write_new(args.output, annotation_template(load_json(args.dataset)))
            print("Annotation template created; all samples remain pending.")
        elif args.command == "validate":
            labels = validate_annotations(load_json(args.dataset), load_json(args.annotations))
            print("Valid annotation document: " + str(len(labels["entries"])) + " entries (not quality approval).")
        elif args.command == "inventory":
            write_new(args.output, inventory(load_json(args.dataset), args.query))
            print("Private topic inventory created; matches still require source review.")
        else:
            result = report(load_json(args.dataset), load_json(args.annotations))
            if args.markdown:
                require(args.output.resolve() != args.markdown.resolve(), "report output paths must differ")
                require(not args.markdown.exists(), "Markdown report already exists")
            write_new(args.output, result)
            if args.markdown:
                write_new(args.markdown, markdown_report(result))
            print("Quality report created; no model calls or business-data writes.")
    except QualityError as exc:
        print("Quality validation failed: " + str(exc), file=sys.stderr)
        return 1
    except FileExistsError:
        print("Quality output already exists. Choose a new path; existing files were not overwritten.", file=sys.stderr)
        return 1
    except Exception:
        # Connection/JSON exceptions can contain passwords, source text, or personal notes.
        print("Quality command failed. Check input schema, dataset identity, private labels, "
              "database availability, and non-existing output paths. No model was called.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
