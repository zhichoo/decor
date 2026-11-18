"""Source dependencies, explicit costs, and quoted subtotal boundaries."""
import copy
import unittest

import test_claim_contract as contract
from claim_fixtures import wire_payload

server = contract.server


class ClaimBoundaryTests(unittest.TestCase):
    def payload(self, text, conclusion, quote=None, **fields):
        claim = {"object_name": (quote or text).split("，")[0].split("。")[0][:24], "author_stance": "赞成", "content_type": "施工做法",
                 "source_scope": "general", "scope_quote": "", "promotion_relation": "independent",
                 "statement": {"text": conclusion, "quote": quote or text}, "condition": None,
                 "price": None, "reasons": [], "alternatives": [], **fields}
        return wire_payload({"claims": [claim], "ambiguities": [], "filter_reason": "none",
            "promotion_context": {"has_promotion": False, "subjects": []}}, text, server.claim_wire)

    def run_payload(self, payload, text):
        return server.partition_claims(payload, text, require_contract=True)

    def test_ambiguous_source_action_cannot_be_saved_by_removing_or_replacing_word(self):
        text = "如果楼层低的话，我还建你仙丹，要不然开窗进小虫。"
        for conclusion in ("楼层低时建议先装纱窗，避免开窗进小虫。", "楼层低时建议提前安装防虫设施。"):
            payload = self.payload(text, conclusion)
            payload["ambiguities"] = [{"type": "transcription", "span": [1, 1], "blocking": "source",
                "blocked_terms": [], "reason": "建议动作本身转写不明"}]
            before = copy.deepcopy(payload)
            clean, dropped, excluded = self.run_payload(payload, text)
            self.assertFalse(clean)
            self.assertIn("dependency", str(excluded))
            self.assertIn("original_conclusion", str(dropped))
            self.assertEqual(payload, before)

    def test_unclear_dimension_cannot_be_saved_by_omitting_the_dimension(self):
        text = "固定一圈2公分的欧松板，再把型材固定上去。"
        payload = self.payload(text, "固定一圈欧松板，再把型材固定上去。")
        payload["ambiguities"] = [{"type": "parameter", "span": [1, 1], "blocking": "source",
            "reason": "尺寸未说明宽还是厚"}]
        clean, _, excluded = self.run_payload(payload, text)
        self.assertFalse(clean)
        self.assertIn("dependency", str(excluded))

    def test_detail_ambiguity_does_not_block_independent_budget_in_same_quote(self):
        text = "预算分成四份各占25%，材料清单中有铝库板。"
        payload = self.payload(text, "预算分成四份，各占25%。")
        payload["ambiguities"] = [{"type": "transcription", "span": [1, 2], "blocking": "terms",
            "blocked_terms": ["铝库板"], "reason": "清单名称不明，不影响独立预算分配"}]
        clean, _, _ = self.run_payload(payload, text)
        self.assertEqual(len(clean), 1)
        payload["claims"][0]["statement"][0] = "预算分成四份，各占25%，并使用铝库板。"
        clean, _, excluded = self.run_payload(payload, text)
        self.assertFalse(clean)
        self.assertIn("dependency", str(excluded))

    def test_source_dependency_uses_selected_offsets_not_all_identical_occurrences(self):
        text = "施工前应检查线路。施工前应检查线路。"
        payload = self.payload(text, "施工前应检查线路。")
        payload["claims"][0]["statement"][1:] = [2, 2]
        payload["ambiguities"] = [{"type": "scope", "span": [1, 1], "blocking": "source",
            "blocked_terms": [], "reason": "第一处对象不明"}]
        clean, _, _ = self.run_payload(payload, text)
        self.assertEqual(len(clean), 1)

    def test_ambiguous_optional_reason_is_removed_without_discarding_clear_core(self):
        text = "施工前应检查线路。这里的原因转写不明。也可请专业人员检查。"
        payload = self.payload(text, "施工前应检查线路。", quote="施工前应检查线路。",
            reasons=[{"text": "原因是材料不兼容", "quote": "这里的原因转写不明。"}],
            alternatives=[{"text": "也可请专业人员检查", "quote": "也可请专业人员检查。"}])
        payload["ambiguities"] = [{"type": "transcription", "span": [2, 2], "blocking": "source",
            "reason": "原因转写不明"}]
        clean, dropped, _ = self.run_payload(payload, text)
        self.assertEqual(len(clean), 1, dropped)
        claim = clean[0]
        self.assertEqual(claim["original_reasons"], [])
        self.assertEqual(claim["alternatives"], ["也可请专业人员检查"])
        self.assertEqual(claim["field_evidence"]["alternatives.0"], [1])
        self.assertEqual(claim["evidence_spans"]["alternatives.0"], [text.index("也可请"), len(text)])
        self.assertNotIn("original_reasons.0", claim["evidence_spans"])
        server.claim_contract.validate_stored_evidence(claim, text)

    def test_missing_or_invalid_ambiguity_blocking_is_not_silently_inferred(self):
        text = "施工前应检查线路。"
        for blocking in (None, "ignore", "terms"):
            payload = self.payload(text, text)
            payload["ambiguities"] = [{"type": "scope", "span": [1, 1], "blocking": blocking,
                "blocked_terms": [], "reason": "测试"}]
            with self.subTest(blocking=blocking), self.assertRaises(ValueError):
                self.run_payload(payload, text)

    def test_forged_source_offsets_are_rejected_not_trusted_from_model(self):
        text = "施工前应检查线路。"
        payload = self.payload(text, text)
        payload["ambiguities"] = [{"type": "scope", "span": [1, 1], "blocking": "source",
            "source_range": [999, 999], "reason": "测试"}]
        with self.assertRaisesRegex(ValueError, "invalid_review_evidence"):
            self.run_payload(payload, text)

    def test_omitted_adjacent_tradeoff_is_excluded_and_preserved_tradeoff_is_kept(self):
        quote = "想省钱可以先装橱柜，再围着柜顶做吊顶。"
        text = quote + "但顶风板会露出个小边，你得接受。"
        payload = self.payload(text, "想省钱可以先装橱柜，再围着柜顶做吊顶。", quote=quote)
        clean, dropped, _ = self.run_payload(payload, text)
        self.assertFalse(clean)
        self.assertIn("explicit_tradeoff_not_preserved", str(dropped))
        payload["claims"][0]["condition"] = ["顶风板会露出个小边，你得接受", 3, 4]
        clean, dropped, _ = self.run_payload(payload, text)
        self.assertEqual(len(clean), 1, dropped)

    def test_unstated_tradeoffs_are_not_invented_and_topic_transition_is_respected(self):
        quote = "先装橱柜，再做吊顶。"
        for text in (quote, quote + "下一个问题是地板，但会多花一千元，你得接受。"):
            clean, dropped, _ = self.run_payload(self.payload(text, quote, quote=quote), text)
            self.assertEqual(len(clean), 1, dropped)

    def test_adjacent_tradeoff_with_units_accepts_exact_equivalence(self):
        quote = "这个方案可以减少施工时间。"
        text = quote + "但会多花一千元，你得接受。"
        payload = self.payload(text, "这个方案可以减少施工时间，但会多花1000元。", quote=text)
        clean, dropped, _ = self.run_payload(payload, text)
        self.assertEqual(len(clean), 1, dropped)

    def test_partial_item_list_cannot_keep_original_group_subtotal(self):
        text = "灯具两千元，插座一千元，窗帘两千五百元，合计五千五百元。"
        payload = self.payload(text, "灯具两千元、窗帘两千五百元，合计五千五百元。")
        clean, dropped, _ = self.run_payload(payload, text)
        self.assertFalse(clean)
        self.assertIn("subtotal_scope_not_preserved", str(dropped))
        payload["claims"][0]["statement"][0] = "灯具两千元、插座一千元、窗帘两千五百元，合计五千五百元。"
        clean, dropped, _ = self.run_payload(payload, text)
        self.assertEqual(len(clean), 1, dropped)

    def test_ambiguous_source_subtotal_is_not_recomputed_or_corrected(self):
        text = "这整组报价中，灯具两千，台座一千，窗帘两千五，合计五千七。"
        payload = self.payload(text, "灯具两千，窗帘两千五，合计五千七。")
        clean, dropped, _ = self.run_payload(payload, text)
        self.assertFalse(clean)
        self.assertIn("subtotal_scope_not_preserved", str(dropped))
        payload["claims"][0]["statement"][0] = "整组报价合计五千七。"
        clean, dropped, _ = self.run_payload(payload, text)
        self.assertEqual(len(clean), 1, dropped)

    def test_optional_mis_scoped_subtotal_is_pruned_not_reassigned_to_core(self):
        core = "施工前应检查线路。"
        bundle = "灯具两千元，插座一千元，窗帘两千五百元，合计五千五百元。"
        text = core + bundle
        payload = self.payload(text, core, quote=core,
            price={"text": "灯具两千元、窗帘两千五百元合计五千五百元", "quote": bundle})
        clean, dropped, _ = self.run_payload(payload, text)
        self.assertEqual(len(clean), 1, dropped)
        self.assertEqual(clean[0]["price_info"], "未提及")
        self.assertNotIn("price_info", clean[0]["field_evidence"])

    def test_single_price_and_dimension_are_not_a_bundle_subtotal(self):
        text = "一百二十平方米的房屋，硬装总价十一万元。"
        payload = self.payload(text, "一百二十平方米房屋，硬装总价十一万元。")
        clean, dropped, _ = self.run_payload(payload, text)
        self.assertEqual(len(clean), 1, dropped)

    def test_v14_remains_readable_offline_but_cannot_enter_live_pipeline(self):
        text = "施工前应检查线路。"
        payload = self.payload(text, text)
        payload["extraction_contract"] = "v14"
        payload["claims"][0]["reasons"] = []
        payload["claims"][0]["alternatives"] = []
        payload["claims"][0].pop("reason")
        payload["claims"][0].pop("alternative")
        historical = server.claim_wire.normalize_historical(payload, text)
        self.assertEqual(historical["claims"][0]["source_quotes"], [text])
        with self.assertRaisesRegex(ValueError, "missing_extraction_contract_v18"):
            self.run_payload(payload, text)
