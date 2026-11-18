#!/usr/bin/env python3
"""Index pairwise reading links, preserving every original card and its provenance."""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
import server
import claim_relations as relations


def private_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with path.open("w", encoding="utf-8") as stream:
        path.chmod(0o600)
        json.dump(value, stream, ensure_ascii=False, indent=2)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--audit-directory", type=Path, help="Refine equivalent/contains/opposite/conditions/numbers findings")
    selection.add_argument("--all", action="store_true", help="Retrieve candidates across all active cards")
    selection.add_argument("--claim-id", action="append", help="Retrieve candidates for the specified cards")
    selection.add_argument("--refine-similar", action="store_true", help="Distinguish equivalent claims within existing similar pairs")
    parser.add_argument("--cache", type=Path, default=ROOT / ".runtime/claim-relations")
    parser.add_argument("--workers", type=int, choices=(1, 2, 3), default=1)
    parser.add_argument("--retry-failed", action="store_true", help="Explicitly retry previously submitted failed/unfinished batches")
    args = parser.parse_args()
    with server.connect() as conn:
        cards = conn.execute("""SELECT c.* FROM claims c JOIN videos v ON v.id=c.video_id
            WHERE c.deleted_at IS NULL AND v.purged_at IS NULL ORDER BY c.id""").fetchall()
        previous = {(row["claim_a_id"], row["claim_b_id"]): row for row in conn.execute("SELECT * FROM claim_relations").fetchall()}
    by_id = {card["id"]: card for card in cards}
    if args.refine_similar:
        pairs = []
        for row in previous.values():
            a, b = by_id.get(row["claim_a_id"]), by_id.get(row["claim_b_id"])
            if row["kind"] == "similar" and a and b and relations.valid_relation(row, by_id):
                pairs.append((a, b))
    elif args.audit_directory:
        baseline = {card["id"]: card for card in json.loads((args.audit_directory / "cards.private.json").read_text())}
        findings = json.loads((args.audit_directory / "findings.private.json").read_text())
        pairs = []
        for row in findings:
            if row["relation"] not in ("equivalent", "contains", "opposite", "conditions", "numbers"):
                continue
            a, b = by_id.get(row["a"]), by_id.get(row["b"])
            if not a or not b or any(relations.fingerprint(card) != relations.fingerprint(baseline.get(card["id"], {})) for card in (a, b)):
                continue
            pairs.append(tuple(sorted((a, b), key=lambda card: card["id"])))
    else:
        pairs = relations.candidate_pairs(cards, None if args.all else set(args.claim_id))
    pairs = sorted({(a["id"], b["id"]): (a, b) for a, b in pairs}.values(), key=lambda pair: (pair[0]["id"], pair[1]["id"]))
    pairs = [(a, b) for a, b in pairs if not ((row := previous.get((a["id"], b["id"])))
             and row["version"] == relations.VERSION and row["fingerprint_a"] == relations.fingerprint(a)
             and row["fingerprint_b"] == relations.fingerprint(b))]
    print(json.dumps({"active_cards": len(cards), "candidate_pairs_to_index": len(pairs), "cards_modified": 0}), flush=True)

    def process(batch):
        signature = hashlib.sha256((relations.VERSION + json.dumps([
            (a["id"], relations.fingerprint(a), b["id"], relations.fingerprint(b)) for a, b in batch
        ])).encode()).hexdigest()
        path = args.cache / (signature + ".private.json")
        cached = json.loads(path.read_text()) if path.exists() else None
        if cached and cached.get("status") == "completed":
            results = cached["results"]
        else:
            if cached and not args.retry_failed:
                return {"failed_batches": 1}
            private_json(path, {"status": "started", "version": relations.VERSION})
            try:
                results = relations.classify(batch, server.call_deepseek, server.parse_deepseek_content)
            except Exception:
                private_json(path, {"status": "failed", "version": relations.VERSION})
                return {"failed_batches": 1}
            private_json(path, {"status": "completed", "version": relations.VERSION, "results": results,
                                "pairs": [{"a": a["id"], "b": b["id"]} for a, b in batch]})
        saved = Counter()
        with server.connect() as conn, conn.transaction():
            for (a, b), result in zip(batch, results):
                if relations.save_relation(conn, a, b, result["kind"], result["reason"]):
                    saved[result["kind"]] += 1
        print(json.dumps({"batch": signature[:8], "indexed": dict(saved)}, ensure_ascii=False), flush=True)
        return saved

    summary = Counter()
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        for result in executor.map(process, [pairs[start:start + 24] for start in range(0, len(pairs), 24)]):
            summary.update(result)
    print(json.dumps({"indexed": dict(summary), "cards_modified": 0}, ensure_ascii=False), flush=True)
    return 1 if summary["failed_batches"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
