"""Release regressions: usable evidence hints and conservative content boundaries."""
import copy
import unittest

import test_claim_contract as contract

server = contract.server


class ClaimReleaseQualityTests(unittest.TestCase):
    def payload(self, statement, title, span):
        return {"extraction_contract": "v18", "promotion_context": {"has_promotion": False, "subjects": []},
                "filter_reason": "none", "ambiguities": [], "claims": [{
                    "object_name": title, "author_stance": "中性陈述", "content_type": "施工做法",
                    "source_scope": "general", "scope_span": None, "promotion_relation": "independent",
                    "statement": [statement, *span], "condition": None, "price": None,
                    "reason": None, "alternative": None}]}

    def test_prompt_bounds_include_only_legal_evidence_without_resegmentation(self):
        for text in ("一万出头，包安装费用需要核对。尾。", "甲，" * 30, "字" * 650, "", " \n"):
            pieces = server.claim_wire.segments(text)
            hints = server.claim_wire.prompt_segments(text)
            self.assertEqual([(p["id"], p["text"]) for p in pieces],
                             [(p["id"], p["text"]) for p in hints])
            for first, hint in enumerate(hints):
                legal = []
                for last in range(first, len(pieces)):
                    quote = text[pieces[first]["start"]:pieces[last]["end"]]
                    if (last - first < 16 and len(quote.strip()) <= 480
                            and len(server.evidence_text(quote)) >= 6):
                        legal.append(last + 1)
                self.assertEqual(hint["allowed_last"], [legal[0], legal[-1]] if legal else None)

    def test_short_price_cannot_start_standalone_but_has_direct_context_option(self):
        hints = server.claim_wire.prompt_segments("一万出头，包安装费用需要核对。")
        self.assertEqual(hints[0]["allowed_last"], [2, 2])
        with self.assertRaisesRegex(ValueError, "evidence_span_size"):
            server.claim_wire.normalize(self.payload("一万出头", "一万出头", [1, 1]),
                                        "一万出头，包安装费用需要核对。")

    def test_known_broken_term_is_excluded_without_model_flag(self):
        text = "直接用瓷砖做泥包贴。施工前应检查线路。"
        payload = self.payload("直接用瓷砖做泥包贴。", "瓷砖", [1, 1])
        payload["claims"] += self.payload("施工前应检查线路。", "检查线路", [2, 2])["claims"]
        before = copy.deepcopy(payload)
        clean, _, excluded = server.partition_claims(payload, text, require_contract=True)
        self.assertEqual([c["object_name"] for c in clean], ["检查线路"])
        self.assertIn("transcription", str(excluded))
        self.assertEqual(payload, before)

    def test_title_can_use_the_grounded_statement_without_being_an_exact_quote(self):
        text = "把你的预算开分成4样，轻工辅料占25%，主材占25%。"
        payload = self.payload("把预算分成4样，轻工辅料占25%，主材占25%。", "预算分成4样", [1, 3])
        clean, dropped, _ = server.partition_claims(payload, text, require_contract=True)
        self.assertEqual(len(clean), 1, dropped)
        payload["claims"][0]["object_name"] = "预算分配确保不超支"
        self.assertFalse(server.partition_claims(payload, text, require_contract=True)[0])

    def test_vague_cost_fragment_dropped_but_price_and_independent_information_keep(self):
        text = "只要一重新找平，费用确实高。"
        payload = self.payload(text, "重新找平", [1, 2])
        payload["claims"][0]["condition"] = ["只要一重新找平", 1, 2]
        clean, _, excluded = server.partition_claims(payload, text, require_contract=True)
        self.assertFalse(clean)
        self.assertIn("fragmentary_cost_opinion", str(excluded))
        for claim in ({"original_conclusion": "重新找平单价40元/平。"},
                      {"original_conclusion": text, "original_reasons": ["需要先拆除原地面。"]},
                      {"original_conclusion": text, "conditions": "地面高差超过两厘米"}):
            self.assertFalse(server.claim_safety.vague_cost_fragment(claim))

    def test_budget_allocation_without_unit_is_not_valid_knowledge(self):
        for text in ("定制占25，定制做柜子。", "定制占25.5，其他项目另算。"):
            payload = self.payload(text.split("，")[0], "定制", [1, 2])
            clean, _, excluded = server.partition_claims(payload, text, require_contract=True)
            self.assertFalse(clean)
            self.assertIn("missing_allocation_unit", str(excluded))

    def test_allocation_units_and_nonallocation_numbers_remain_valid(self):
        for text in ("定制占25%，其他项目另算。", "柜体占3平方米。", "定制预算占两成。", "装修预算分成4份。"):
            payload = self.payload(text, text[:2], [1, len(server.claim_wire.segments(text))])
            clean, dropped, _ = server.partition_claims(payload, text, require_contract=True)
            self.assertEqual(len(clean), 1, (text, dropped))

    def test_unsupported_guarantee_is_excluded_but_source_assertion_not_verified(self):
        text = "把整体预算分成4份，你这么装没毛病。"
        payload = self.payload("把整体预算分成4份，这么装才能不超支。", "整体预算", [1, 2])
        clean, _, excluded = server.partition_claims(payload, text, require_contract=True)
        self.assertFalse(clean)
        self.assertIn("unsupported_certainty", str(excluded))
        # Keeping an explicit author claim does not mean its guarantee is factual.
        source = "按此预算分配，作者保证不超支。"
        clean, dropped, _ = server.partition_claims(
            self.payload(source, "预算分配", [1, 2]), source, require_contract=True)
        self.assertEqual(len(clean), 1, dropped)

    def test_optional_unsupported_guarantee_does_not_destroy_clear_core(self):
        text = "施工前应检查线路。检查线路有助于发现接线问题。"
        payload = self.payload("施工前应检查线路。", "检查线路", [1, 1])
        payload["claims"][0]["reason"] = ["确保接线绝对安全。", 2, 2]
        clean, _, _ = server.partition_claims(payload, text, require_contract=True)
        self.assertEqual(len(clean), 1)
        self.assertEqual(clean[0]["original_reasons"], [])
        server.claim_contract.validate_stored_evidence(clean[0], text)

    def test_prompt_carries_legal_bounds_and_uses_same_wire_protocol(self):
        prompt = server.build_extract_prompt({"title": "test", "creator": "test", "platform": "test",
            "source_url": "https://example.invalid", "transcript_text": "一万出头，包安装费用需要核对。"})
        self.assertIn('"allowed_last":[2,2]', prompt)
        self.assertIn('"extraction_contract":"v18"', prompt)
        self.assertIn("一个预算方案合成一张", prompt)


if __name__ == "__main__":
    unittest.main()
