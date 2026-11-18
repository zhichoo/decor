"""Read-only guide content: structure validation and knowledge-card reference resolution.

Guides live in content/guides/<slug>.json under version control. This module never
touches the model or writes to the database; the private API and the public
exporter both call ``resolve`` so they apply the same visibility rules.
"""
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
CONTENT_DIR = ROOT / "content" / "guides"
SCHEMA_VERSION = 1
SLUG_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
BLOCK_KINDS = frozenset(("points", "pitfalls", "questions", "documents", "differing", "other", "text"))
BLOCK_TYPES = frozenset(("paragraph", "list", "table"))
PENDING_TEXT = "资料待补充"
FINGERPRINT_FIELDS = ("video_id", "object_name", "original_conclusion", "conditions", "stance",
                      "author_stance", "source_quotes")
REF = re.compile(r"\[\^([a-z0-9]+-\d+)\]")
NOTE_LINK = re.compile(r"\]\(note:([a-z0-9]+-\d+)\)")
CLAIM_TOKEN = re.compile(r"\{\{claim:([A-Za-z0-9_-]+)\}\}")
_cache = {}


def _json_list(value):
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return []
    return [item for item in value or [] if isinstance(item, str)]


def claim_evidence(claim):
    """The card fields a guide statement depends on, from a DB row, API card or snapshot card."""
    evidence = {key: claim.get(key) for key in FINGERPRINT_FIELDS}
    evidence["source_quotes"] = _json_list(evidence["source_quotes"])
    evidence["id"] = claim["id"]
    return evidence


def claim_fingerprint(claim):
    evidence = claim_evidence(claim)
    payload = json.dumps({key: evidence[key] for key in FINGERPRINT_FIELDS}, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def iter_items(guide):
    """Yield (location, text) for every reader-facing string that may carry note references."""
    for chapter in guide.get("chapters", []):
        for index, text in enumerate(chapter.get("intro", [])):
            yield f"{chapter.get('id')}/intro/{index}", text
        for section in chapter.get("sections", []):
            for block in section.get("blocks", []):
                if block.get("type") == "paragraph":
                    yield block.get("id"), block.get("text", "")
                for item in block.get("items", []):
                    if "cells" in item:
                        yield item.get("id"), " ".join(item["cells"])
                    else:
                        yield item.get("id"), item.get("text", "")


def validate(guide):
    """Return a list of structure errors; an empty list means the guide can be published."""
    errors = []
    for key in ("id", "slug", "title", "schema_version", "content_version", "updated_at", "chapters", "notes", "checklist"):
        if key not in guide:
            errors.append(f"missing field: {key}")
    if errors:
        return errors
    if guide["schema_version"] != SCHEMA_VERSION:
        errors.append(f"unsupported schema_version: {guide['schema_version']}")
    if not SLUG_PATTERN.match(str(guide["slug"])):
        errors.append("invalid slug")
    ids, sections = set(), set()

    def unique(value, where):
        if not value:
            errors.append(f"missing id: {where}")
        elif value in ids:
            errors.append(f"duplicate id: {value}")
        ids.add(value)

    for chapter in guide["chapters"]:
        unique(chapter.get("id"), "chapter")
        for section in chapter.get("sections", []):
            unique(section.get("id"), "section")
            sections.add(section.get("number"))
            if not section.get("blocks"):
                errors.append(f"empty section: {section.get('id')}")
            for block in section.get("blocks", []):
                unique(block.get("id"), f"block in {section.get('id')}")
                if block.get("kind") not in BLOCK_KINDS or block.get("type") not in BLOCK_TYPES:
                    errors.append(f"invalid block kind/type: {block.get('id')}")
                for item in block.get("items", []):
                    unique(item.get("id"), f"item in {block.get('id')}")
    notes = guide["notes"]
    used = set()
    for location, text in iter_items(guide):
        for ref in REF.findall(text):
            used.add(ref)
            if ref not in notes:
                errors.append(f"missing note {ref} at {location}")
    for key, note in notes.items():
        targets = NOTE_LINK.findall(note.get("text", ""))
        for target in targets:
            if target not in notes:
                errors.append(f"note {key} links to missing note {target}")
        tokens = set(CLAIM_TOKEN.findall(note.get("text", "")))
        refs = {ref.get("claim_id") for ref in note.get("claim_refs", [])}
        if tokens != refs:
            errors.append(f"note {key} claim tokens and claim_refs differ")
        if any(not ref.get("fingerprint") for ref in note.get("claim_refs", [])):
            errors.append(f"note {key} has a claim reference without fingerprint")
    linked = {target for note in notes.values() for target in NOTE_LINK.findall(note.get("text", ""))}
    for key in sorted(set(notes) - used - linked):
        errors.append(f"unused note: {key}")
    for group in guide["checklist"].get("groups", []):
        for subgroup in group.get("subgroups", []):
            for item in subgroup.get("items", []):
                unique(item.get("id"), "checklist item")
                if not item.get("text"):
                    errors.append(f"empty checklist item: {item.get('id')}")
                for number in item.get("sections", []):
                    if number not in sections:
                        errors.append(f"checklist item {item.get('id')} points to missing section {number}")
    documents = guide["checklist"].get("documents") or {}
    width = len(documents.get("header", []))
    for index in documents.get("checkable_rows", []):
        if not isinstance(index, int) or not 0 <= index < len(documents.get("rows", [])):
            errors.append(f"documents checkable row {index} does not exist")
    for index, row in enumerate(documents.get("rows", [])):
        if len(row) != width:
            errors.append(f"documents row {index + 1} has {len(row)} cells, header has {width}")
        if documents.get("header", [""])[-1] == "出处" and row:
            for number in re.findall(r"\d\.\d", row[-1]):
                if number not in sections:
                    errors.append(f"documents row {index + 1} points to missing section {number}")
    return errors


def resolve(guide, claims_by_id):
    """Build the reader payload.

    ``claims_by_id`` holds only cards visible under the caller's rules (active card,
    source video not purged). A reference to a missing card, or to a card whose
    fingerprinted fields changed, is withheld; statements that rest solely on such
    evidence are replaced with a short pending notice. Returns (payload, issues).
    """
    issues, notes, visible_claims = [], {}, {}
    for key, note in guide["notes"].items():
        valid, invalid = [], []
        for ref in note.get("claim_refs", []):
            claim = claims_by_id.get(ref["claim_id"])
            if claim is None:
                invalid.append(ref["claim_id"])
                issues.append({"note": key, "claim_id": ref["claim_id"], "problem": "missing"})
            elif claim_fingerprint(claim) != ref["fingerprint"]:
                invalid.append(ref["claim_id"])
                issues.append({"note": key, "claim_id": ref["claim_id"], "problem": "changed"})
            else:
                valid.append(ref["claim_id"])
                visible_claims[ref["claim_id"]] = claim
        status = "ok"
        if invalid:
            status = "stale" if note.get("claim_only") and not valid else "partial"
        notes[key] = {"label": note["label"], "text": PENDING_TEXT if status == "stale" else note["text"],
                      "status": status, "claims": valid}
    stale = {key for key, note in notes.items() if note["status"] == "stale"}

    def rests_on_stale(text):
        refs = REF.findall(text)
        return bool(refs) and all(ref in stale for ref in refs)

    chapters = json.loads(json.dumps(guide["chapters"]))
    for chapter in chapters:
        for section in chapter["sections"]:
            for block in section["blocks"]:
                if block["type"] == "paragraph" and rests_on_stale(block["text"]):
                    block.update(text=PENDING_TEXT, pending=True)
                    issues.append({"item": block["id"], "problem": "pending"})
                for item in block.get("items", []):
                    if "cells" in item:
                        if rests_on_stale(" ".join(item["cells"])):
                            item.update(cells=[item["cells"][0], *[PENDING_TEXT] * (len(item["cells"]) - 1)], pending=True)
                            issues.append({"item": item["id"], "problem": "pending"})
                    elif rests_on_stale(item["text"]):
                        item.update(text=PENDING_TEXT, pending=True)
                        issues.append({"item": item["id"], "problem": "pending"})
    payload = {key: guide[key] for key in ("id", "slug", "title", "schema_version", "content_version",
                                            "updated_at", "scope", "notice", "checklist") if key in guide}
    payload.update(chapters=chapters, notes=notes, claims=visible_claims)
    return payload, issues


def guide_claim_ids(guide):
    return sorted({ref["claim_id"] for note in guide["notes"].values() for ref in note.get("claim_refs", [])})


def load_guide(slug, directory=None):
    """Load and validate one guide file; cached by modification time."""
    if not SLUG_PATTERN.match(slug or ""):
        return None
    path = Path(directory or CONTENT_DIR) / f"{slug}.json"
    try:
        stamp = path.stat().st_mtime_ns
    except OSError:
        return None
    cached = _cache.get(path)
    if cached and cached[0] == stamp:
        return cached[1]
    guide = json.loads(path.read_text(encoding="utf-8"))
    errors = validate(guide)
    if errors or guide["slug"] != slug:
        raise ValueError(f"guide {slug} failed validation: {(errors or ['slug mismatch'])[0]}")
    _cache[path] = (stamp, guide)
    return guide


def list_guides(directory=None):
    result = []
    for path in sorted(Path(directory or CONTENT_DIR).glob("*.json")):
        guide = load_guide(path.stem, directory)
        if guide:
            result.append({"slug": guide["slug"], "title": guide["title"], "updated_at": guide["updated_at"]})
    return result
