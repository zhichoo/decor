"""Same-pass source wording, local quotation scope, and fine evidence boundaries."""
import copy
import unittest

import test_claim_contract as contract
from claim_fixtures import wire_payload

server = contract.server


class HistoricalSourceClauseTests(unittest.TestCase):
    """Preserve the v17 experiment without imposing deletion-only on new output."""
    def payload(self, text, statement, quote=None, **fields):
        claim = {"object_name": "装修做法", "author_stance": "赞成", "content_type": "施工做法",
                 "source_scope": "general", "scope_quote": "", "promotion_relation": "independent",
                 "statement": {"text": statement, "quote": quote or text}, "condition": None,
                 "price": None, "reasons": [], "alternatives": [], **fields}
        return wire_payload({"claims": [claim], "ambiguities": [], "filter_reason": "none",
            "promotion_context": {"has_promotion": False, "subjects": []}}, text, type("HistoricalWire", (), {"VERSION": "v17", "segments": staticmethod(server.claim_wire.segments)}))

    def run_payload(self, payload, text):
        return server._partition_claims(server.claim_wire.normalize_historical(payload, text), text, require_contract=True)

    def test_unmarked_asr_noun_substitution_is_not_a_supported_summary(self):
        for text, statement in [
            ("地面高低不平，直接用瓷砖做泥包贴基础不允许。", "地面高低不平，直接用瓷砖胶泥包贴基础不允许。"),
            ("台面加多层实木的镶体，包安装一共六千。", "台面加多层实木柜体，包安装一共六千。"),
            ("这里使用的是某种甲构件。", "这里使用的是某种乙构件。"),
        ]:
            with self.subTest(text=text):
                clean, _, excluded = self.run_payload(self.payload(text, statement), text)
                self.assertFalse(clean)
                self.assertIn("source_text_not_preserved", str(excluded))

    def test_deleting_oral_filler_keeps_source_word_order(self):
        text = "你切记啊，施工前一定要检查一下线路，然后再施工。"
        clean, dropped, _ = self.run_payload(self.payload(text, "施工前要检查线路，再施工。"), text)
        self.assertEqual(len(clean), 1, dropped)

    def test_negation_cannot_be_deleted_to_reverse_action(self):
        text = "不要拆除承重墙体。"
        clean, _, excluded = self.run_payload(self.payload(text, "拆除承重墙体。"), text)
        self.assertFalse(clean)
        self.assertIn("source_text_not_preserved", str(excluded))

    def test_unit_equivalence_still_allowed_and_wrong_scale_still_excluded(self):
        text = "板材厚度三十毫米。"
        clean, dropped, _ = self.run_payload(self.payload(text, "板材厚度3厘米。"), text)
        self.assertEqual(len(clean), 1, dropped)
        clean, _, excluded = self.run_payload(self.payload(text, "板材厚度30厘米。"), text)
        self.assertFalse(clean)
        self.assertIn("unsupported_field_numeric_detail", str(excluded))

    def test_rewritten_optional_reason_pruned_without_losing_clear_core(self):
        text = "施工前应检查线路。这里的原因未说明。"
        payload = self.payload(text, "施工前应检查线路。", quote="施工前应检查线路。",
            reasons=[{"text": "避免材料接触不良", "quote": "这里的原因未说明。"}])
        clean, dropped, _ = self.run_payload(payload, text)
        self.assertEqual(len(clean), 1, dropped)
        self.assertEqual(clean[0]["original_reasons"], [])
        self.assertEqual(clean[0]["source_quotes"], ["施工前应检查线路。"])
        server.claim_contract.validate_stored_evidence(clean[0], text)

    def test_clause_boundary_separates_noisy_question_from_clear_answer_and_condition(self):
        text = "先做瓦瓜修的木，你切记，如果你赶工期的情况下，你可以完全先做木匠。前提是拆改不能太多。"
        answer = "如果你赶工期的情况下，你可以完全先做木匠。"
        payload = self.payload(text, answer, quote=answer,
            condition={"text": "拆改不能太多", "quote": "前提是拆改不能太多。"})
        payload["ambiguities"] = [{"type": "transcription", "span": [1, 1], "blocking": "source",
                                   "reason": "开头问句转写不清"}]
        clean, dropped, _ = self.run_payload(payload, text)
        self.assertEqual(len(clean), 1, dropped)
        self.assertNotIn("先做瓦瓜修的木", str(clean[0]["source_quotes"]))

    def test_key_parameter_cannot_be_downgraded_to_terms_mode(self):
        text = "固定一圈2公分的欧松板，再固定型材。"
        payload = self.payload(text, "固定欧松板，再固定型材。")
        payload["ambiguities"] = [{"type": "parameter", "span": [1, 1], "blocking": "terms",
            "blocked_terms": ["2公分"], "reason": "宽度还是厚度不明"}]
        with self.assertRaisesRegex(ValueError, "parameter_requires_source_blocking"):
            self.run_payload(payload, text)

    def test_clause_subspan_cannot_hide_explicit_huaxing_condition(self):
        text = "你户型方正的话，你就做局部拆改，两千元足够。"
        quote = "你就做局部拆改，两千元足够。"
        payload = self.payload(text, "局部拆改，两千元足够。", quote=quote)
        clean, _, excluded = self.run_payload(payload, text)
        self.assertFalse(clean)
        self.assertIn("explicit_condition_not_preserved", str(excluded))
        payload["claims"][0]["condition"] = ["户型方正", 1, 1]
        clean, dropped, _ = self.run_payload(payload, text)
        self.assertEqual(len(clean), 1, dropped)

    def test_quotation_keeps_preceding_base_and_wall_cabinet_sizes(self):
        scope = "地柜五米，吊柜三米。"
        quote = "台面加多层实木柜体，包安装一共六千元。"
        text = scope + quote
        payload = self.payload(text, quote, quote=quote, object_name="橱柜报价", content_type="价格信息")
        clean, _, excluded = self.run_payload(payload, text)
        self.assertFalse(clean)
        self.assertIn("quotation_size_scope_not_preserved", str(excluded))
        payload["claims"][0]["condition"] = ["地柜五米，吊柜三米", 1, 2]
        clean, dropped, _ = self.run_payload(payload, text)
        self.assertEqual(len(clean), 1, dropped)

    def test_equivalent_scope_units_are_supported(self):
        text = "地柜五米，吊柜三米。台面加多层实木柜体，包安装一共六千元。"
        payload = self.payload(text, "台面加多层实木柜体，包安装一共六千元。",
            quote="台面加多层实木柜体，包安装一共六千元。", object_name="橱柜报价",
            condition={"text": "地柜500厘米，吊柜300厘米", "quote": "地柜五米，吊柜三米。"})
        clean, dropped, _ = self.run_payload(payload, text)
        self.assertEqual(len(clean), 1, dropped)

    def test_quotation_cannot_borrow_another_objects_equal_quantity(self):
        text = "地柜五米，吊柜三米。台面加多层实木柜体，包安装一共六千元。"
        claim = {"object_name": "橱柜报价", "original_conclusion": "包安装一共六千元",
                 "conditions": "台面五米，吊柜三米", "evidence_spans": {"original_conclusion": [text.index("台面"), len(text)]}}
        issues = server.claim_safety.price_scope_issues(claim, text, server.numeric_evidence_values)
        self.assertTrue(issues)
        self.assertTrue(any("地柜" in issue["scope"] for issue in issues))

    def test_identical_consequence_at_other_offset_does_not_import_its_condition(self):
        text = "如果预算有限，就建议保留原来的灯具。就建议保留原来的灯具。"
        payload = self.payload(text, "建议保留原来的灯具。", quote="就建议保留原来的灯具。")
        payload["claims"][0]["statement"][1:] = [3, 3]
        clean, dropped, _ = self.run_payload(payload, text)
        self.assertEqual(len(clean), 1, dropped)

    def test_unrelated_size_or_explicit_topic_change_not_imported_into_price(self):
        quote = "封阳台普通窗子一共两千元。"
        for prefix in ("地柜五米，吊柜三米。", "窗户总长五米。下一个报价是另外一套窗，"):
            text = prefix + quote
            clean, dropped, _ = self.run_payload(self.payload(text, quote, quote=quote,
                object_name="窗子报价", content_type="价格信息"), text)
            self.assertEqual(len(clean), 1, dropped)

    def test_fine_segments_do_not_split_formatted_arabic_numbers(self):
        text = "施工预算1,000元，先核对项目。"
        pieces = server.claim_wire.segments(text)
        self.assertEqual(pieces[0]["text"], "施工预算1,000元，")
        self.assertEqual("".join(p["text"] for p in pieces), text)

    def test_historical_v16_uses_its_original_segmentation_and_live_rejects_it(self):
        text = "先做瓦瓜修的木，如果赶工期可以先做木匠。"
        payload = self.payload(text, "如果赶工期可以先做木匠。")
        payload["extraction_contract"] = "v16"
        payload["claims"][0]["statement"][1:] = [1, 1]
        before = copy.deepcopy(payload)
        historical = server.claim_wire.normalize_historical(payload, text)
        self.assertEqual(historical["claims"][0]["source_quotes"], [text])
        self.assertNotIn("source_text_mode", historical["claims"][0])
        self.assertEqual(payload, before)
        with self.assertRaisesRegex(ValueError, "missing_extraction_contract_v18"):
            server.partition_claims(payload, text, require_contract=True)

    def test_model_cannot_forge_or_turn_off_source_text_mode(self):
        text = "施工前应检查线路。"
        payload = self.payload(text, text)
        payload["claims"][0]["source_text_mode"] = "free_rewrite"
        with self.assertRaisesRegex(ValueError, "mixed_extraction_contract"):
            self.run_payload(payload, text)

    def test_demonstrative_topic_marker_is_not_a_substantive_condition(self):
        text = "这块的话，瓷砖加辅料加工费两万元。"
        quote = "瓷砖加辅料加工费两万元。"
        clean, dropped, _ = self.run_payload(self.payload(text, quote, quote=quote), text)
        self.assertEqual(len(clean), 1, dropped)

    def test_rewrite_check_alone_cannot_detect_literal_transcription_corruption(self):
        text = "直接用瓷砖做泥包贴。"
        self.assertEqual(server.claim_safety.source_rewrite_errors(text, text, server.numeric_evidence_values), [])

    def test_explicit_unclear_term_links_different_clause_evidence(self):
        text = "这里说一定要胶浆。不胶浆的话，它就会两层皮就是容易空。"
        quote = "不胶浆的话，它就会两层皮就是容易空。"
        payload = self.payload(text, quote, quote=quote)
        payload["ambiguities"] = [{"type": "transcription", "span": [1, 1], "blocking": "source",
                                   "blocked_terms": ["胶浆"], "reason": "胶浆具体材料与动作不明"}]
        clean, _, excluded = self.run_payload(payload, text)
        self.assertFalse(clean)
        self.assertIn("dependency", str(excluded))


if __name__ == "__main__":
    unittest.main()
