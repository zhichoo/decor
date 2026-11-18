"""Guide content: structure checks, card-reference degradation, Markdown import, public export and reading UI."""
from functools import partial
from http.server import ThreadingHTTPServer
import copy
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "scripts"))
import guide_catalog  # noqa: E402
import import_guide_markdown as importer  # noqa: E402

spec = importlib.util.spec_from_file_location("decor_public_export_guides", ROOT / "scripts/export_public.py")
exporter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(exporter)
sys.path.insert(0, str(ROOT / "tests"))
from test_public_site import QuietHandler, fixture  # noqa: E402


def sample_guide(claims):
    """A two-section guide: one statement rests only on a card, one on a mixed note."""
    first, second = claims[0], claims[1]
    return {
        "id": "guide-all-inclusive-company", "slug": "all-inclusive-company", "title": "测试指南",
        "schema_version": 1, "content_version": "1", "updated_at": "2026-11-18", "scope": "范围", "notice": "声明",
        "chapters": [{"id": "ch0", "number": "0", "title": "先选模式", "intro": ["先对项目。[^c0-3]"], "sources": [],
                      "sections": [{"id": "s0.1", "number": "0.1", "title": "预算", "tags": ["半包"], "blocks": [
                          {"type": "list", "kind": "pitfalls", "label": "避坑", "id": "s0.1-pitfalls-1", "items": [
                              {"id": "s0.1-pitfalls-1-1", "text": "只靠知识卡支撑的说法。[^c0-1]"},
                              {"id": "s0.1-pitfalls-1-2", "text": "有法规依据的说法。[^c0-2]"}]},
                          {"type": "table", "kind": "text", "id": "s0.1-text-1", "header": ["位置", "预留"],
                           "items": [{"id": "s0.1-text-1-1", "cells": ["门口", "插座 [^c0-1]"]}]}]}]}],
        "notes": {
            "c0-1": {"label": "1", "text": "知识库：预算 {{claim:%s}}。" % first["id"], "claim_only": True,
                     "claim_refs": [{"claim_id": first["id"], "fingerprint": guide_catalog.claim_fingerprint(first)}]},
            "c0-2": {"label": "2", "text": "管理办法第三十二条；另见 {{claim:%s}}，以及[注释 3](note:c0-3)。" % second["id"],
                     "claim_only": False,
                     "claim_refs": [{"claim_id": second["id"], "fingerprint": guide_catalog.claim_fingerprint(second)}]},
            "c0-3": {"label": "3", "text": "[示例来源](https://example.com/a?x=1)"},
        },
        "checklist": {"title": "核对清单", "note": "只用于收集信息。", "documents": {
                          "header": ["时间", "材料", "里面要写明", "出处"], "rows": [["签约时", "合同正文", "双方名称；开工日期", "0.1"],
                                   ["签约时", "施工图纸", "平面图；水电图", "0.1"]], "checkable_rows": [0],
                          "lead": "签字前逐份对照。", "source": "按[管理办法](https://example.com/law)。"},
                      "groups": [{"id": "g1", "title": "一、签约前", "subgroups": [{"title": "范围", "items": [
                          {"id": "g1-1", "text": "预算写进合同", "sections": ["0.1"], "tags": ["半包"]},
                          {"id": "g1-2", "text": "看过工地", "sections": [], "tags": []}]}]}]},
    }


class GuideCatalogTests(unittest.TestCase):
    def setUp(self):
        self.claims = fixture()[2]
        self.guide = sample_guide(self.claims)
        self.by_id = {claim["id"]: claim for claim in self.claims}

    def test_published_content_file_is_valid(self):
        guide = json.loads((guide_catalog.CONTENT_DIR / "all-inclusive-company.json").read_text())
        self.assertEqual(guide_catalog.validate(guide), [])
        self.assertEqual(len(guide["chapters"]), 9)
        self.assertEqual(sum(len(chapter["sections"]) for chapter in guide["chapters"]), 42)

    def test_valid_references_resolve_without_issues_or_private_fields(self):
        payload, issues = guide_catalog.resolve(self.guide, self.by_id)
        self.assertEqual(issues, [])
        self.assertEqual(set(payload["claims"]), {self.claims[0]["id"], self.claims[1]["id"]})
        self.assertNotIn("fingerprint", json.dumps(payload))
        self.assertNotIn("claim_only", json.dumps(payload))

    def test_missing_card_withholds_statements_that_rest_only_on_it(self):
        del self.by_id[self.claims[0]["id"]]
        payload, issues = guide_catalog.resolve(self.guide, self.by_id)
        items = payload["chapters"][0]["sections"][0]["blocks"][0]["items"]
        self.assertEqual(items[0]["text"], guide_catalog.PENDING_TEXT)
        self.assertTrue(items[0]["pending"])
        self.assertIn("有法规依据", items[1]["text"])
        row = payload["chapters"][0]["sections"][0]["blocks"][1]["items"][0]
        self.assertEqual(row["cells"], ["门口", guide_catalog.PENDING_TEXT])
        self.assertEqual(payload["notes"]["c0-1"], {"label": "1", "text": guide_catalog.PENDING_TEXT, "status": "stale", "claims": []})
        self.assertNotIn(self.claims[0]["id"], payload["claims"])
        self.assertIn({"note": "c0-1", "claim_id": self.claims[0]["id"], "problem": "missing"}, issues)

    def test_changed_card_in_mixed_note_keeps_statement_but_hides_card(self):
        self.by_id[self.claims[1]["id"]] = {**self.claims[1], "original_conclusion": "作者后来改了说法"}
        payload, issues = guide_catalog.resolve(self.guide, self.by_id)
        self.assertEqual(payload["notes"]["c0-2"]["status"], "partial")
        self.assertEqual(payload["notes"]["c0-2"]["claims"], [])
        self.assertNotIn(self.claims[1]["id"], payload["claims"])
        self.assertIn("有法规依据", payload["chapters"][0]["sections"][0]["blocks"][0]["items"][1]["text"])
        self.assertEqual(issues, [{"note": "c0-2", "claim_id": self.claims[1]["id"], "problem": "changed"}])

    def test_fingerprint_ignores_fields_the_guide_does_not_depend_on(self):
        changed = {**self.claims[0], "topic_tags": ["其他"], "created_at": 1, "relation_counts": {"similar": 3}}
        self.assertEqual(guide_catalog.claim_fingerprint(changed), guide_catalog.claim_fingerprint(self.claims[0]))
        as_text = {**self.claims[0], "source_quotes": json.dumps(self.claims[0]["source_quotes"], ensure_ascii=False)}
        self.assertEqual(guide_catalog.claim_fingerprint(as_text), guide_catalog.claim_fingerprint(self.claims[0]))

    def test_structure_errors_are_reported(self):
        broken = copy.deepcopy(self.guide)
        broken["chapters"][0]["sections"][0]["blocks"][0]["items"][1]["text"] = "缺注释。[^c0-9]"
        broken["checklist"]["groups"][0]["subgroups"][0]["items"][0]["sections"] = ["9.9"]
        broken["checklist"]["groups"][0]["subgroups"][0]["items"][1]["id"] = "g1-1"
        broken["notes"]["c0-2"]["text"] = "没有卡片标记"
        broken["checklist"]["documents"]["checkable_rows"] = [7]
        broken["checklist"]["documents"]["rows"].append(["签约时", "图纸", "8.8"])
        broken["checklist"]["documents"]["rows"].append(["签约时", "图纸", "页数", "8.8"])
        errors = guide_catalog.validate(broken)
        joined = "\n".join(errors)
        for expected in ("missing note c0-9", "missing section 9.9", "duplicate id: g1-1", "claim tokens and claim_refs differ",
                         "documents checkable row 7 does not exist", "documents row 3 has 3 cells",
                         "documents row 4 points to missing section 8.8"):
            self.assertIn(expected, joined)

    def test_load_guide_rejects_invalid_files_and_slugs(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "all-inclusive-company.json"
            path.write_text(json.dumps(self.guide, ensure_ascii=False))
            self.assertEqual(guide_catalog.load_guide("all-inclusive-company", directory)["title"], "测试指南")
            self.assertIsNone(guide_catalog.load_guide("../secret", directory))
            broken = {**self.guide, "notes": {}}
            path.write_text(json.dumps(broken, ensure_ascii=False))
            with self.assertRaises(ValueError):
                guide_catalog.load_guide("all-inclusive-company", directory)


class MarkdownImportTests(unittest.TestCase):
    DRAFT = """# 样稿

---

## 4 比报价

总价只有在项目相同时才能比。[^1]

### 4.1 统一口径　`半包重点`

**要点**：先对项目。[^2]

**避坑**

- 只看总价。[^1]
- 漏项。

| 位置 | 预留 |
| --- | --- |
| 门口 | 插座 [^2] |

---

## 签约前核对清单（第 4 章）

- [ ] 不导入

## 注释

[^1]: 媒体报道，见第 5 章注释 3。

[^2]: 知识库：说法 `claim_0123abcd`；见注释 1。
"""

    def test_sections_blocks_and_note_links(self):
        chapters, notes, _ = importer.parse_part("c4", self.DRAFT)
        chapter = chapters[0]
        self.assertEqual(chapter["intro"], ["总价只有在项目相同时才能比。[^c4-1]"])
        section = chapter["sections"][0]
        self.assertEqual((section["id"], section["title"], section["tags"]), ("s4.1", "统一口径", ["半包重点"]))
        kinds = [(block["kind"], block["type"]) for block in section["blocks"]]
        self.assertEqual(kinds, [("points", "paragraph"), ("pitfalls", "list"), ("pitfalls", "table")])
        self.assertEqual(section["blocks"][1]["items"][0], {"text": "只看总价。[^c4-1]", "id": "s4.1-pitfalls-1-1"})
        self.assertEqual(notes["c4-1"]["text"], "媒体报道，见[第 5 章注释 3](note:c5-3)。")
        self.assertIn("[注释 1](note:c4-1)", notes["c4-2"]["text"])

    def test_short_card_ids_resolve_to_full_ids_with_fingerprints(self):
        _, notes, _ = importer.parse_part("c4", self.DRAFT)
        card = {"id": "claim_0123abcdef", "video_id": "v1", "object_name": "说法", "original_conclusion": "结论",
                "conditions": "未提及", "stance": "明确推荐", "author_stance": "赞成", "source_quotes": []}
        importer.resolve_short_claims(notes, lambda ids: {"0123abcd": card} if ids == ["0123abcd"] else {})
        self.assertIn("{{claim:claim_0123abcdef}}", notes["c4-2"]["text"])
        self.assertEqual(notes["c4-2"]["claim_refs"], [{"claim_id": card["id"], "fingerprint": guide_catalog.claim_fingerprint(card)}])
        self.assertTrue(notes["c4-2"]["claim_only"])
        with self.assertRaises(SystemExit):
            importer.resolve_short_claims(importer.parse_part("c4", self.DRAFT)[1], lambda ids: {})


class GuideExportTests(unittest.TestCase):
    def test_snapshot_resolves_guides_against_public_cards_only(self):
        sources, videos, claims = fixture()
        guide = sample_guide(claims)
        claims[0]["deleted_at"] = 10
        snapshot = exporter.make_snapshot(sources, videos, claims, guides=[guide])
        payload = snapshot["guides"]["all-inclusive-company"]
        self.assertEqual(set(payload["claims"]), {claims[1]["id"]})
        self.assertEqual(payload["notes"]["c0-1"]["status"], "stale")
        self.assertNotIn("extraction_run_id", json.dumps(payload["claims"]))
        self.assertEqual(exporter.make_snapshot(sources, videos, claims)["guides"], {})

    def test_site_ships_guide_assets(self):
        sources, videos, claims = fixture()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "site"
            exporter.build_site(exporter.make_snapshot(sources, videos, claims, guides=[sample_guide(claims)]), output)
            document = (output / "index.html").read_text()
            self.assertTrue((output / "guides.js").is_file() and (output / "guides.css").is_file())
            self.assertRegex(document, r'guides\.js\?v=[0-9a-f]{16}')
            self.assertLess(document.index("guides.js"), document.index("public-client.js"))


class GuideBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from playwright.sync_api import sync_playwright
        cls.directory = tempfile.TemporaryDirectory(prefix="decor-guide-ui-")
        cls.sites = {}
        sources, videos, claims = fixture()
        for name, guides in (("with", [sample_guide(claims)]), ("without", [])):
            output = Path(cls.directory.name) / name
            snapshot = exporter.make_snapshot(sources, videos, claims, guides=guides)
            if name == "without":
                snapshot.pop("guides")  # an older snapshot written before guides existed
            exporter.build_site(snapshot, output)
            server = ThreadingHTTPServer(("127.0.0.1", 0), partial(QuietHandler, directory=str(output)))
            threading.Thread(target=server.serve_forever, daemon=True).start()
            cls.sites[name] = server
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch(headless=True, channel="chrome")

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()
        for server in cls.sites.values():
            server.shutdown()
            server.server_close()
        cls.directory.cleanup()

    def open(self, site, hash_="#guide", **options):
        context = self.browser.new_context(**{"viewport": {"width": 1440, "height": 900}, **options})
        self.addCleanup(context.close)
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.route("**/api/**", lambda route: (errors.append("api request " + route.request.url), route.abort()))
        page.goto(f"http://127.0.0.1:{self.sites[site].server_port}/{hash_}")
        self.addCleanup(lambda: self.assertEqual(errors, []))
        return page

    def test_notes_cards_and_source_round_trip_restore_reading_state(self):
        page = self.open("with")
        page.wait_for_selector("#guide-view .guide-section")
        self.assertTrue(page.locator('.nav-item[data-view="guide"]').is_visible())
        page.locator(".guide-list .guide-ref").first.click()
        note = page.locator(".guide-list .guide-note").first
        self.assertIn("知识库", note.inner_text())
        page.locator(".guide-list .guide-ref").nth(1).click()
        mixed = page.locator('.guide-note[data-guide-note-key="c0-2"]')
        mixed.locator(".guide-note-jump").click()
        self.assertIn("示例来源", mixed.locator(".guide-note-nested").inner_text())
        self.assertEqual(mixed.locator('a[href^="https://example.com"]').get_attribute("rel"), "noopener noreferrer")
        chip = note.locator(".guide-claim")
        chip.click()
        page.wait_for_selector("#guide-claims-dialog[open] .claim-card")
        # Anchored popover under the chip, not a centred modal; clicking outside closes it.
        chip_box, card_box = chip.bounding_box(), page.locator("#guide-claims-dialog").bounding_box()
        self.assertAlmostEqual(card_box["y"], chip_box["y"] + chip_box["height"] + 8, delta=2)
        self.assertFalse(page.locator("#guide-claims-dialog").evaluate("dialog => dialog.matches(':modal')"))
        page.mouse.click(5, 5)
        self.assertFalse(page.locator("#guide-claims-dialog").evaluate("dialog => dialog.open"))
        chip.click()
        chip.click()
        self.assertFalse(page.locator("#guide-claims-dialog").evaluate("dialog => dialog.open"))
        chip.click()
        page.keyboard.press("Escape")
        self.assertFalse(page.locator("#guide-claims-dialog").evaluate("dialog => dialog.open"))
        chip.click()
        page.locator("#guide-claims-dialog .claim-source-action").click()
        page.wait_for_selector("#detail-view.active")
        self.assertFalse(page.locator("#guide-claims-dialog").evaluate("dialog => dialog.open"))
        page.go_back()
        page.wait_for_selector("#guide-view.active .guide-section")
        self.assertEqual(page.locator(".guide-note").count(), 2)

    def test_paragraph_notes_open_in_place_and_toc_marks_current_chapter(self):
        # Paragraph items hold a block-level notes container; a <p> wrapper would be split by the parser.
        page = self.open("with")
        page.wait_for_selector("#guide-view .guide-section")
        page.locator(".guide-intro .guide-ref").click()
        self.assertTrue(page.locator('.guide-intro .guide-note[data-guide-note-key="c0-3"]').is_visible())
        page.locator(".guide-intro .guide-ref").click()
        self.assertEqual(page.locator(".guide-intro .guide-note").count(), 0)
        page.wait_for_selector('.guide-toc-chapter.is-current[data-toc-chapter="ch0"]')
        self.assertTrue(page.locator('.guide-toc-link[data-guide-section="s0.1"]').is_visible())
        self.assertTrue(page.locator(".guide-toc details").evaluate("el => el.open"))
        page.locator(".guide-toc summary").click()  # folds to chapter titles, never hides them
        self.assertTrue(page.locator('.guide-toc-chapter > .guide-toc-link[data-guide-section="ch0"]').is_visible())
        self.assertFalse(page.locator('.guide-toc-link[data-guide-section="s0.1"]').is_visible())
        page.locator(".guide-toc summary").click()
        self.assertTrue(page.locator('.guide-toc-link[data-guide-section="s0.1"]').is_visible())

    def test_checklist_persists_resets_copies_and_links_back(self):
        page = self.open("with")
        page.context.grant_permissions(["clipboard-read", "clipboard-write"])
        page.locator('[data-guide-tab="checklist"]').click()
        page.locator('[data-guide-check="g1-1"]').check()
        page.reload()
        page.locator('[data-guide-tab="checklist"]').click()
        self.assertTrue(page.locator('[data-guide-check="g1-1"]').is_checked())
        self.assertIn("已核对 1", page.locator(".guide-check-toolbar").inner_text())
        self.assertIn("签字前逐份对照", page.locator(".guide-docs-lead").inner_text())
        self.assertEqual(page.locator('.guide-docs-source a[href="https://example.com/law"]').count(), 1)
        self.assertEqual(page.locator(".guide-doc-points input").count(), 2)  # only the contract body is ticked
        self.assertIn("平面图；水电图", page.locator(".guide-doc-contents").inner_text())
        page.locator(".guide-doc-points input").first.check()
        self.assertIn("合同正文 1 / 2", page.locator(".guide-check-toolbar").inner_text())
        page.locator("[data-guide-copy]").click()
        copied = page.evaluate("navigator.clipboard.readText()")
        self.assertIn("[已核对] 预算写进合同（见 0.1）", copied)
        self.assertIn("签约时｜合同正文（见 0.1）\n  [已核对] 双方名称\n  [未核对] 开工日期", copied)
        self.assertIn("签约时｜施工图纸（见 0.1）\n  要写明：平面图；水电图", copied)
        page.locator("[data-guide-reset]").click()
        self.assertTrue(page.locator('[data-guide-check="g1-1"]').is_checked())
        page.locator("[data-guide-reset]").click()
        self.assertFalse(page.locator('[data-guide-check="g1-1"]').is_checked())
        page.locator('.guide-section-link[data-guide-section="s0.1"]').first.click()
        page.wait_for_function("document.activeElement && document.activeElement.id === 'guide-s0.1-title'")

    def test_reading_works_without_browser_storage(self):
        page = self.open("with")
        page.add_init_script("Object.defineProperty(window, 'localStorage', { get() { throw new Error('blocked'); } })")
        page.reload()
        page.locator('[data-guide-tab="checklist"]').click()
        page.locator('[data-guide-check="g1-2"]').check()
        self.assertIn("不能保存勾选", page.locator(".guide-check-note").inner_text())
        self.assertIn("已核对 1", page.locator(".guide-check-toolbar").inner_text())

    def test_older_snapshot_hides_guide_entry_and_bookmark_falls_back(self):
        page = self.open("without")
        page.wait_for_function("document.querySelector('#overview-view').classList.contains('active')")
        self.assertFalse(page.locator('.nav-item[data-view="guide"]').is_visible())

    def test_mobile_layout_has_no_horizontal_scroll(self):
        page = self.open("with", viewport={"width": 390, "height": 844})
        page.wait_for_selector("#guide-view .guide-section")
        self.assertLessEqual(page.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth"), 0)
        self.assertTrue(page.locator('.nav-item[data-view="guide"]').is_visible())

    def test_mobile_toc_is_a_left_drawer(self):
        page = self.open("with", viewport={"width": 390, "height": 844})
        page.wait_for_selector("#guide-view .guide-section")
        toc = page.locator("#guide-toc")
        self.assertFalse(toc.is_visible())
        page.locator("[data-guide-toc-toggle]").click()
        page.wait_for_function("document.querySelector('#guide-toc').getBoundingClientRect().left >= 0")
        self.assertTrue(page.locator('#guide-toc .guide-toc-link[data-guide-section="s0.1"]').is_visible())
        page.locator('#guide-toc .guide-toc-link[data-guide-section="s0.1"]').click()
        page.wait_for_function("getComputedStyle(document.querySelector('#guide-toc')).visibility === 'hidden'")
        self.assertEqual(page.locator("[data-guide-toc-toggle]").get_attribute("aria-expanded"), "false")
        page.locator("[data-guide-toc-toggle]").click()
        page.locator(".guide-toc-backdrop").click(position={"x": 370, "y": 400})
        page.wait_for_function("getComputedStyle(document.querySelector('#guide-toc')).visibility === 'hidden'")
        page.locator("[data-guide-toc-toggle]").click()
        page.keyboard.press("Escape")
        page.wait_for_function("getComputedStyle(document.querySelector('#guide-toc')).visibility === 'hidden'")


if __name__ == "__main__":
    unittest.main()
