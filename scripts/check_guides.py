#!/usr/bin/env python3
"""Read-only guide check: structure, missing or changed knowledge-card references.

Exit code 0 means the structure is valid and every card reference still matches;
1 means structure errors (publishing is blocked); 2 means reference issues
(publishing still works, affected statements show a pending notice).
"""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "scripts"))
import guide_catalog  # noqa: E402


def visible_claims(claim_ids):
    import psycopg2
    from psycopg2.extras import RealDictCursor
    from init_db import database_url
    with psycopg2.connect(database_url(), cursor_factory=RealDictCursor) as conn:
        conn.set_session(readonly=True, isolation_level="REPEATABLE READ")
        with conn.cursor() as cursor:
            cursor.execute("""SELECT c.* FROM claims c JOIN videos v ON v.id=c.video_id
                WHERE c.id = ANY(%s) AND c.deleted_at IS NULL AND v.purged_at IS NULL""", (claim_ids,))
            return {row["id"]: row for row in cursor.fetchall()}


def check(guide, claims_by_id):
    errors = guide_catalog.validate(guide)
    if errors:
        return {"slug": guide.get("slug"), "structure_errors": errors, "reference_issues": []}
    _, issues = guide_catalog.resolve(guide, claims_by_id)
    return {"slug": guide["slug"], "structure_errors": [], "reference_issues": issues}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dir", type=Path, default=guide_catalog.CONTENT_DIR)
    parser.add_argument("--skip-db", action="store_true", help="only check structure")
    args = parser.parse_args()
    reports, status = [], 0
    for path in sorted(args.dir.glob("*.json")):
        guide = json.loads(path.read_text(encoding="utf-8"))
        if args.skip_db:
            report = {"slug": guide.get("slug"), "structure_errors": guide_catalog.validate(guide), "reference_issues": []}
        else:
            ids = guide_catalog.guide_claim_ids(guide) if "notes" in guide else []
            report = check(guide, visible_claims(ids))
        if report["structure_errors"]:
            status = 1
        elif report["reference_issues"] and status == 0:
            status = 2
        reports.append(report)
    print(json.dumps(reports, ensure_ascii=False, indent=1))
    raise SystemExit(status)


if __name__ == "__main__":
    main()
