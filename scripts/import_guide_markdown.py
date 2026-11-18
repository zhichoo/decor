#!/usr/bin/env python3
"""Convert the guide Markdown drafts into content/guides/<slug>.json.

The drafts in md/guide-draft-*.md stay the editing source until the content is
finalised. Knowledge-card references written as `claim_xxxxxxxx` (short ids) are
resolved against the local database (read-only) and stored with a content
fingerprint, so later checks can tell when a referenced card changed.
"""
import argparse
from datetime import date
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "scripts"))
import guide_catalog  # noqa: E402

SLUG = "all-inclusive-company"
DRAFTS = (  # (part key, file); a part shares one footnote numbering
    ("c01", "guide-draft-ch0-1-20261116.md"),
    ("c23", "guide-draft-ch2-3-20261117.md"),
    ("c4", "guide-draft-ch4-20261117.md"),
    ("c5", "guide-draft-ch5-20261117.md"),
    ("c6", "guide-draft-ch6-20261117.md"),
    ("c7", "guide-draft-ch7-20261117.md"),
    ("c8", "guide-draft-ch8-20261117.md"),
)
APPENDIX = "guide-draft-appendix-20261117.md"
CHAPTER_PART = {"0": "c01", "1": "c01", "2": "c23", "3": "c23", "4": "c4", "5": "c5", "6": "c6", "7": "c7", "8": "c8"}
LABEL_KINDS = {"要点": "points", "避坑": "pitfalls", "要问": "questions", "要材料": "documents", "不同说法": "differing"}
SKIPPED_H2 = re.compile(r"^(签约前核对清单|核对清单|本章新增来源)")
SHORT_CLAIM = re.compile(r"`claim_([0-9a-f]{8})`")


def split_notes(text):
    body, _, notes = text.partition("\n## 注释\n")
    definitions = {}
    for match in re.finditer(r"^\[\^(\d+)\]: (.*)$", notes, re.M):
        number = int(match.group(1))
        if number in definitions:
            raise SystemExit(f"duplicate note definition [^{number}]")
        definitions[number] = match.group(2).strip()
    return body, definitions


def ref_tokens(text, part):
    return re.sub(r"\[\^(\d+)\]", lambda m: "[^%s-%s]" % (part, m.group(1)), text)


def note_links(text, part):
    """Turn cross references into note: links the renderer can follow."""
    def chapter_ref(match):
        chapter, numbers = match.group(1), match.group(2)
        target = CHAPTER_PART[chapter]
        first = re.split(r"[–、]", numbers)[0]
        return "[第 %s 章注释 %s](note:%s-%s)" % (chapter, numbers, target, first)
    text = re.sub(r"第 (\d) 章注释 (\d+(?:[–、]\d+)*)", chapter_ref, text)
    return re.sub(r"(?<![章\[])注释 (\d+)",
                  lambda m: "[注释 %s](note:%s-%s)" % (m.group(1), part, m.group(1)), text)


def table_rows(lines):
    rows = [[cell.strip() for cell in line.strip().strip("|").split("|")] for line in lines]
    rows = [row for row in rows if not all(re.fullmatch(r":?-{3,}:?", cell) for cell in row)]
    return rows[0], rows[1:]


def parse_blocks(lines, part, section_id):
    """Group a section's Markdown lines into labelled blocks with stable item ids."""
    blocks, label = [], None
    index = 0
    counters = {}

    def add(block):
        kind = LABEL_KINDS.get(block.get("label"), "other" if block.get("label") else "text")
        block["kind"] = kind
        counters[kind] = counters.get(kind, 0) + 1
        block["id"] = "%s-%s-%d" % (section_id, kind, counters[kind])
        for number, item in enumerate(block.get("items", []), 1):
            item["id"] = "%s-%d" % (block["id"], number)
        blocks.append(block)

    while index < len(lines):
        line = lines[index].rstrip()
        if not line.strip():
            index += 1
            continue
        alone = re.fullmatch(r"\*\*([^*]+)\*\*", line)
        inline = re.match(r"^\*\*([^*]+)\*\*：(.*)$", line)
        if alone:
            label = alone.group(1)
            index += 1
            continue
        if inline:
            add({"type": "paragraph", "label": inline.group(1), "text": ref_tokens(inline.group(2), part)})
            label = None
            index += 1
            continue
        if re.match(r"^(- |\d+\. )", line):
            ordered = bool(re.match(r"^\d+\. ", line))
            items = []
            while index < len(lines) and re.match(r"^(- |\d+\. )", lines[index]):
                items.append({"text": ref_tokens(re.sub(r"^(- |\d+\. )", "", lines[index].rstrip()), part)})
                index += 1
            add({"type": "list", "label": label, "ordered": ordered, "items": items})
            continue
        if line.startswith("|"):
            chunk = []
            while index < len(lines) and lines[index].startswith("|"):
                chunk.append(ref_tokens(lines[index], part))
                index += 1
            header, rows = table_rows(chunk)
            add({"type": "table", "label": label, "header": header, "items": [{"cells": row} for row in rows]})
            continue
        if line.startswith((">", "#", "---")):
            raise ValueError("unexpected Markdown inside section %s: %s" % (section_id, line[:40]))
        add({"type": "paragraph", "label": label, "text": ref_tokens(line, part)})
        index += 1
    for block in blocks:
        if not block.get("label"):
            block.pop("label", None)
    return blocks


def parse_part(part, text):
    body, notes = split_notes(text)
    chapters, notice = [], None
    chapter = section = None
    buffer = []
    skipping = False

    def flush():
        nonlocal buffer
        if section is not None:
            section["blocks"] = parse_blocks(buffer, part, "s" + section["number"])
        elif chapter is not None:
            chapter["intro"] = [ref_tokens(line, part) for line in buffer if line.strip() and line.strip() != "---"]
        buffer = []

    for line in body.splitlines():
        if line.startswith("> ") and chapter is None:
            notice = re.sub(r"^页面顶部声明：", "", line[2:].strip())
            continue
        heading = re.match(r"^(##|###) (.+)$", line)
        if heading and heading.group(1) == "##":
            flush()
            title = heading.group(2).strip()
            skipping = bool(SKIPPED_H2.match(title))
            chapter_heading = re.match(r"^(\d) (.+)$", title)
            section = None
            if chapter_heading:
                chapter = {"id": "ch" + chapter_heading.group(1), "number": chapter_heading.group(1),
                           "title": chapter_heading.group(2), "intro": [], "sections": []}
                chapters.append(chapter)
            elif skipping:
                chapter = None  # checklist/source tables belong to the appendix and source lists
            else:
                raise ValueError("unexpected chapter heading: " + title)
            continue
        if skipping or chapter is None:
            continue
        if heading:
            flush()
            match = re.match(r"^(\d\.\d) (.+?)((?:[　 ]*`[^`]+`)*)$", heading.group(2).strip())
            if not match:
                raise ValueError("unexpected section heading: " + line)
            section = {"id": "s" + match.group(1), "number": match.group(1), "title": match.group(2).strip(),
                       "tags": re.findall(r"`([^`]+)`", match.group(3))}
            chapter["sections"].append(section)
            continue
        if line.strip() == "---":
            continue
        buffer.append(line)
    flush()
    note_items = {}
    for number, value in notes.items():
        note_items["%s-%d" % (part, number)] = {"label": str(number), "text": note_links(value, part)}
    return chapters, note_items, notice


def parse_appendix(text):
    groups, documents, lead, source = [], [], [], []
    group = subgroup = None
    in_documents = False
    for line in text.splitlines():
        if line.startswith("## "):
            title = line[3:].strip()
            in_documents = title == "要拿到的材料"
            if not in_documents:
                group = {"id": "g%d" % (len(groups) + 1), "title": title, "subgroups": []}
                groups.append(group)
                subgroup = None
            continue
        if line.startswith("### ") and group:
            subgroup = {"title": line[4:].strip(), "items": []}
            group["subgroups"].append(subgroup)
            continue
        if line.startswith("- [ ] "):
            if subgroup is None:
                subgroup = {"title": "", "items": []}
                group["subgroups"].append(subgroup)
            content = line[6:].strip()
            tags = re.findall(r"`([^`]+)`", content)
            textual = re.sub(r"\s*`[^`]+`", "", content).strip()
            subgroup["items"].append({
                "text": textual,
                "sections": [tag for tag in tags if re.fullmatch(r"\d\.\d", tag)],
                "tags": [tag for tag in tags if not re.fullmatch(r"\d\.\d", tag)],
            })
            continue
        if in_documents and line.startswith("|"):
            documents.append(line)
        elif in_documents and line.strip():
            (source if documents else lead).append(line.strip())
    for group in groups:
        number = 0
        for subgroup in group["subgroups"]:
            for item in subgroup["items"]:
                number += 1
                item["id"] = "%s-%d" % (group["id"], number)
    header, rows = table_rows(documents)
    # A bold document name marks a row whose contents are ticked item by item on the page.
    checkable = [index for index, row in enumerate(rows) if len(row) > 1 and re.fullmatch(r"\*\*.+\*\*", row[1])]
    for index in checkable:
        rows[index][1] = rows[index][1][2:-2]
    return groups, {"header": header, "rows": rows, "checkable_rows": checkable,
                    "lead": " ".join(lead), "source": " ".join(source)}


def source_tables(text):
    """Return the chapter's “本章新增来源” rows: code, description, Markdown link."""
    match = re.search(r"\n## 本章新增来源\n(.*?)(?=\n---|\n## )", text, re.S)
    if not match:
        return []
    lines = [line for line in match.group(1).splitlines() if line.startswith("|")]
    if not lines:
        return []
    _, rows = table_rows(lines)
    return [{"code": row[0], "text": row[1], "link": row[2]} for row in rows if len(row) >= 3]


def resolve_short_claims(notes, lookup):
    short_ids = sorted({short for note in notes.values() for short in SHORT_CLAIM.findall(note["text"])})
    found = lookup(short_ids)
    missing = [short for short in short_ids if short not in found]
    if missing:
        raise SystemExit("Knowledge cards not found or not visible: " + ", ".join(missing))
    for note in notes.values():
        claims = []
        def replace(match):
            claim = found[match.group(1)]
            if claim["id"] not in claims:
                claims.append(claim["id"])
            return "{{claim:%s}}" % claim["id"]
        note["text"] = SHORT_CLAIM.sub(replace, note["text"])
        if claims:
            note["claim_refs"] = [{"claim_id": key, "fingerprint": guide_catalog.claim_fingerprint(
                next(value for value in found.values() if value["id"] == key))} for key in claims]
            # A note that only carries knowledge-card evidence loses its basis when those cards change.
            note["claim_only"] = note["text"].startswith("知识库")


def database_lookup(short_ids):
    import psycopg2
    from psycopg2.extras import RealDictCursor
    from init_db import database_url
    with psycopg2.connect(database_url(), cursor_factory=RealDictCursor) as conn:
        conn.set_session(readonly=True)
        with conn.cursor() as cursor:
            cursor.execute("""SELECT c.* FROM claims c JOIN videos v ON v.id=c.video_id
                WHERE c.deleted_at IS NULL AND v.purged_at IS NULL AND substr(c.id, 7, 8) = ANY(%s)""", (short_ids,))
            rows = cursor.fetchall()
    found = {}
    for row in rows:
        short = row["id"][6:14]
        if short in found:
            raise SystemExit("Ambiguous short card id: " + short)
        found[short] = guide_catalog.claim_evidence(row)
    return found


def build(draft_dir, lookup, updated_at):
    chapters, notes, sources, notice = [], {}, [], None
    for part, name in DRAFTS:
        text = (draft_dir / name).read_text(encoding="utf-8")
        part_chapters, part_notes, part_notice = parse_part(part, text)
        for chapter in part_chapters:
            chapter["sources"] = source_tables(text) if chapter is part_chapters[-1] else []
        chapters.extend(part_chapters)
        notes.update(part_notes)
        notice = notice or part_notice
    resolve_short_claims(notes, lookup)
    groups, documents = parse_appendix((draft_dir / APPENDIX).read_text(encoding="utf-8"))
    guide = {
        "id": "guide-" + SLUG, "slug": SLUG, "title": "选装修公司（全包／半包）指南",
        "schema_version": guide_catalog.SCHEMA_VERSION, "content_version": updated_at.replace("-", ""),
        "updated_at": updated_at,
        "scope": "从选承包方式、定范围、筛公司、比报价、核合同，到施工验收、交接售后，每一步要问什么、要拿到什么材料。",
        "notice": notice or "",
        "chapters": chapters, "notes": notes,
        "checklist": {"title": "核对清单",
                      "note": "清单用来收集信息、对照合同；打完勾不代表公司可靠，也不代表合同没有问题。",
                      "groups": groups, "documents": documents},
    }
    errors = guide_catalog.validate(guide)
    if errors:
        raise SystemExit("Guide structure errors:\n" + "\n".join(errors))
    return guide


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--drafts", type=Path, default=ROOT / "md")
    parser.add_argument("--output", type=Path, default=guide_catalog.CONTENT_DIR / f"{SLUG}.json")
    parser.add_argument("--updated-at", default=date.today().isoformat())
    args = parser.parse_args()
    guide = build(args.drafts, database_lookup, args.updated_at)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(guide, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    sections = sum(len(chapter["sections"]) for chapter in guide["chapters"])
    claims = sum(len(note.get("claim_refs", [])) for note in guide["notes"].values())
    items = sum(len(sub["items"]) for group in guide["checklist"]["groups"] for sub in group["subgroups"])
    print(json.dumps({"output": str(args.output), "chapters": len(guide["chapters"]), "sections": sections,
                      "notes": len(guide["notes"]), "claim_refs": claims, "checklist_items": items},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
