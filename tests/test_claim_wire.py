"""Segment references, historical evidence pairs, and live-pipeline boundaries."""
import copy
import json
import unittest

import test_claim_contract as contract

server = contract.server


class SegmentEvidenceTests(unittest.TestCase):
    text = "只有预算有限，才建议保留原来的灯具。\r\n施工前应检查线路。后期收口按参照线反推。"

    def payload(self, span=(4, 4)):
        return {"extraction_contract": "v18", "promotion_context": {"has_promotion": False, "subjects": []},
                "filter_reason": "none", "ambiguities": [], "claims": [{
                    "object_name": "检查线路", "author_stance": "赞成", "content_type": "验收要求",
                    "source_scope": "general", "scope_span": None, "promotion_relation": "independent",
                    "statement": ["施工前应检查线路。", *span], "condition": None, "price": None,
                    "reason": None, "alternative": None}]}

    def test_partition_preserves_every_byte_and_offsets(self):
        for text in (self.text, "", "  \n", "字" * 513, "甲，" * 201, "甲。\n乙！\r\n丙"):
            pieces = server.claim_wire.segments(text)
            self.assertEqual("".join(piece["text"] for piece in pieces), text)
            end = 0
            for index, piece in enumerate(pieces, 1):
                self.assertEqual(piece["id"], index)
                self.assertEqual(piece["start"], end)
                self.assertEqual(piece["text"], text[piece["start"]:piece["end"]])
                self.assertLessEqual(len(piece["text"]), server.claim_wire.MAX_SEGMENT_CHARS)
                end = piece["end"]
            self.assertEqual(end, len(text))

    def test_program_resolves_original_newline_span_without_mutating_input(self):
        payload = self.payload((1, 4))
        before = copy.deepcopy(payload)
        normalized = server.claim_wire.normalize(payload, self.text)
        self.assertEqual(payload, before)
        claim = normalized["claims"][0]
        self.assertEqual(claim["source_quotes"], ["只有预算有限，才建议保留原来的灯具。\r\n施工前应检查线路。"])
        self.assertEqual(claim["field_evidence"], {"object_name": [0], "original_conclusion": [0]})

    def test_valid_new_protocol_reaches_live_partition(self):
        clean, dropped, excluded = server.partition_claims(self.payload(), self.text, require_contract=True)
        self.assertEqual((dropped, excluded), ([], []))
        self.assertEqual(clean[0]["source_quotes"], ["施工前应检查线路。"])
        self.assertEqual(clean[0]["evidence_contract"], server.claim_contract.VERSION)

    def test_prompt_shows_ids_not_character_offsets_or_ambiguous_empty_arrays(self):
        prompt = server.build_extract_prompt({"title": "test", "creator": "test", "platform": "test",
            "source_url": "https://example.invalid", "transcript_text": self.text})
        self.assertNotIn('"start":', prompt)
        self.assertNotIn('"end":', prompt)
        self.assertIn('"id":', prompt)
        self.assertIn("不能是 []", prompt)
        self.assertIn("不是字数或字符位置", prompt)

    def test_invalid_ranges_and_mixed_protocols_fail_closed(self):
        for span in ([0, 0], [-1, 1], [3, 2], [True, 1], [1.0, 1], [1, 999], [1], [1, 1, 1]):
            payload = self.payload()
            payload["claims"][0]["statement"] = ["施工前应检查线路。", *span]
            with self.subTest(span=span), self.assertRaises(ValueError):
                server.partition_claims(payload, self.text, require_contract=True)
        for field, value in (("scope_quote", "施工前应检查线路。"), ("field_evidence", {})):
            payload = self.payload()
            payload["claims"][0][field] = value
            with self.assertRaisesRegex(ValueError, "mixed_extraction_contract"):
                server.claim_wire.normalize(payload, self.text)
        old = LegacyEvidencePairTests().payload()
        with self.assertRaisesRegex(ValueError, "missing_extraction_contract_v18"):
            server.partition_claims(old, LegacyEvidencePairTests.text, require_contract=True)

    def test_span_size_and_quote_budget_are_not_silently_truncated(self):
        for text, span in (("原文中有清楚的施工建议。" * 20, (1, 17)), ("字" * 600, (1, 5)), ("短。", (1, 1))):
            with self.subTest(span=span), self.assertRaises(ValueError):
                server.claim_wire.normalize(self.payload(span), text)
        text = "施工前应检查线路。首先清理基层浮灰。还应核对设计图纸。实际费用是三百元。"
        payload = self.payload((1, 1))
        payload["claims"][0].update(reason=["清理基层浮灰", 2, 2],
                                     alternative=["核对设计图纸", 3, 3], price=["三百元", 4, 4])
        with self.assertRaisesRegex(ValueError, "too_many_source_quotes"):
            server.claim_wire.normalize(payload, text)

    def test_title_evidence_only_available_to_promotion_context(self):
        payload = self.payload()
        payload["promotion_context"] = {"has_promotion": True, "subjects": [{"name": "产品", "span": [0, 0]}]}
        normalized = server.claim_wire.normalize(payload, self.text, title="产品推广购买套餐")
        self.assertEqual(normalized["promotion_context"]["subjects"][0]["quote"], "产品推广购买套餐")
        payload["claims"][0]["scope_span"] = [0, 0]
        with self.assertRaisesRegex(ValueError, "invalid_evidence_span"):
            server.claim_wire.normalize(payload, self.text, title="产品推广购买套餐")

    def test_scope_and_ambiguity_are_resolved_from_original_spans(self):
        payload = self.payload()
        payload["claims"][0].update(source_scope="case", scope_span=[4, 4])
        payload["ambiguities"] = [{"type": "scope", "span": [4, 4], "blocking": "source", "reason": "范围不清", "blocked_terms": []}]
        clean, _, excluded = server.partition_claims(payload, self.text, require_contract=True)
        self.assertFalse(clean)
        self.assertTrue(excluded)
        payload["ambiguities"][0]["quote"] = "施工前应检查线路。"
        with self.assertRaisesRegex(ValueError, "invalid_review_evidence"):
            server.claim_wire.normalize(payload, self.text)

    def test_valid_number_reference_still_cannot_change_units(self):
        payload = self.payload((1, 1))
        payload["claims"][0]["object_name"] = "石膏板厚度"
        payload["claims"][0]["statement"][0] = "石膏板厚度建议采用9厘米。"
        clean, _, excluded = server.partition_claims(payload, "石膏板厚度建议采用9毫米。", require_contract=True)
        self.assertFalse(clean)
        self.assertIn("unsupported_field_numeric_detail", str(excluded))

    def test_json_stop_does_not_allow_partial_or_repaired_payload(self):
        for content in ('{"claims": [{"statement": ["test",1,1]}]', '{"claims":[]} trailing',
                        'prefix {"claims":[]}', '{"claims":[]}{"claims":[]}', '```json\n{"claims":[]}\n```'):
            response = json.dumps({"choices": [{"finish_reason": "stop", "message": {"content": content}}]})
            with self.subTest(content=content), self.assertRaisesRegex(ValueError, "deepseek_content_not_json"):
                server.parse_deepseek_content(response)


class LegacyEvidencePairTests(unittest.TestCase):
    text = "吸水率高的砖要先泡水两小时。不泡水容易出现空鼓。预算是三百元。另一个步骤是铺完留缝两毫米。"

    def payload(self):
        return {"extraction_contract": "v12", "promotion_context": {"has_promotion": False, "subjects": []},
                "filter_reason": "none", "ambiguities": [], "claims": [{
                    "object_name": "高吸水率瓷砖泡水", "author_stance": "赞成", "content_type": "施工做法",
                    "source_scope": "general", "scope_quote": "", "promotion_relation": "independent",
                    "statement": {"text": "吸水率高的瓷砖铺前需泡水两小时。", "quote": "吸水率高的砖要先泡水两小时。"},
                    "condition": {"text": "吸水率高的瓷砖", "quote": "吸水率高的砖要先泡水两小时。"},
                    "reasons": [{"text": "未泡水容易空鼓", "quote": "不泡水容易出现空鼓。"}],
                    "price": None, "alternatives": []}]}

    def run_payload(self, payload):
        return server._partition_claims(server.claim_wire.normalize_legacy(payload, self.text), self.text, require_contract=True)

    def test_program_assigns_ids_and_field_indexes_without_mutation(self):
        payload = self.payload()
        before = copy.deepcopy(payload)
        normalized = server.claim_wire.normalize_legacy(payload, self.text)
        claim = normalized["claims"][0]
        self.assertEqual(claim["claim_id"], "c1")
        self.assertEqual(claim["field_evidence"], {"object_name": [0], "original_conclusion": [0],
                                                "conditions": [0], "original_reasons.0": [1]})
        self.assertEqual(payload, before)
        clean, dropped, excluded = self.run_payload(payload)
        self.assertEqual(len(clean), 1)
        self.assertEqual((dropped, excluded), ([], []))

    def test_live_pipeline_rejects_previous_canonical_protocol(self):
        payload = server.claim_wire.normalize_legacy(self.payload(), self.text)
        with self.assertRaisesRegex(ValueError, "missing_extraction_contract_v18"):
            server.partition_claims(payload, self.text, require_contract=True)

    def test_statement_cannot_supply_quote_list_or_old_bindings(self):
        for value in (["吸水率高的砖要先泡水两小时。"], 0, None):
            payload = self.payload()
            payload["claims"][0]["statement"]["quote"] = value
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "quality_check_failed"):
                self.run_payload(payload)
        payload = self.payload()
        payload["claims"][0]["field_evidence"] = {}
        with self.assertRaisesRegex(ValueError, "mixed_extraction_contract"):
            self.run_payload(payload)

    def test_fabricated_optional_quote_fails_before_optional_pruning(self):
        payload = self.payload()
        payload["claims"][0]["price"] = {"text": "三百元", "quote": "预算是三百元！"}
        with self.assertRaisesRegex(ValueError, "quality_check_failed"):
            self.run_payload(payload)

    def test_line_breaks_cannot_be_silently_repaired(self):
        payload = self.payload()
        payload["claims"][0]["statement"]["quote"] = "吸水率高的砖要先泡水两小时。不泡水容易出现空鼓。"
        transcript = self.text.replace("。不泡水", "。\n不泡水")
        with self.assertRaisesRegex(ValueError, "quality_check_failed"):
            server._partition_claims(server.claim_wire.normalize_legacy(payload, transcript), transcript, require_contract=True)

    def test_quote_budget_does_not_silently_drop_condition_or_optional_information(self):
        payload = self.payload()
        payload["claims"][0]["price"] = {"text": "三百元", "quote": "预算是三百元。"}
        payload["claims"][0]["alternatives"] = [{"text": "留缝两毫米", "quote": "另一个步骤是铺完留缝两毫米。"}]
        with self.assertRaisesRegex(ValueError, "too_many_source_quotes"):
            self.run_payload(payload)

    def test_condition_numeric_error_still_excludes_whole_card(self):
        payload = self.payload()
        payload["claims"][0]["condition"]["text"] = "吸水率高于百分之十的瓷砖"
        clean, _, excluded = self.run_payload(payload)
        self.assertFalse(clean)
        self.assertIn("unsupported_field_numeric_detail:conditions", str(excluded))

    def test_unsupported_optional_number_is_pruned_not_borrowed(self):
        payload = self.payload()
        payload["claims"][0]["price"] = {"text": "三百元", "quote": "不泡水容易出现空鼓。"}
        clean, dropped, _ = self.run_payload(payload)
        self.assertEqual(len(clean), 1)
        self.assertEqual(clean[0]["price_info"], "未提及")
        self.assertIn("unsupported_optional_field", str(dropped))

    def test_ambiguity_ids_are_optional_but_terms_still_propagate(self):
        payload = self.payload()
        payload["ambiguities"] = [{"type": "parameter", "quote": "吸水率高的砖要先泡水两小时。",
                                   "reason": "测试疑点传播", "blocked_terms": ["泡水"]}]
        clean, _, excluded = self.run_payload(payload)
        self.assertFalse(clean)
        self.assertIn("dependency", str(excluded))

    def test_multiple_conclusions_and_extra_pair_fields_are_not_accepted(self):
        for value in ([self.payload()["claims"][0]["statement"]],
                      {**self.payload()["claims"][0]["statement"], "extra": "ignored?"}):
            payload = self.payload()
            payload["claims"][0]["statement"] = value
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "invalid_evidence_pair"):
                self.run_payload(payload)
