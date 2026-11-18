"""Same-response ambiguity dependencies and source-backed titles in v18."""
import copy
import unittest

import test_claim_contract as contract

server = contract.server


class AmbiguityDependencyTests(unittest.TestCase):
    def payload(self, statement, title, span):
        return {"extraction_contract": "v18", "promotion_context": {"has_promotion": False, "subjects": []},
                "filter_reason": "none", "ambiguities": [], "claims": [{
                    "object_name": title, "author_stance": "赞成", "content_type": "施工做法",
                    "source_scope": "general", "scope_span": None, "promotion_relation": "independent",
                    "statement": [statement, *span], "condition": None, "price": None,
                    "reason": None, "alternative": None}]}

    def run_payload(self, payload, text):
        return server.partition_claims(payload, text, require_contract=True)

    def issue(self):
        return {"type": "transcription", "span": [1, 1], "blocking": "source", "blocked_terms": ["胶浆"],
                "reason": "施工动作及材料不清楚"}

    def test_term_in_other_bound_quote_blocks_even_when_summary_removes_it(self):
        text = "一定要在半干砂浆上面一定要胶浆。不胶浆的话，它就会两层皮就是容易空。高吸水率瓷砖要先泡水。"
        payload = self.payload("这种做法能防止空鼓。", "容易空", [2, 3])
        payload["ambiguities"] = [self.issue()]
        payload["claims"].append({**copy.deepcopy(payload["claims"][0]), "object_name": "瓷砖",
                                  "statement": ["吸水率高的瓷砖铺贴前需要泡水。", 4, 4]})
        clean, _, excluded = self.run_payload(payload, text)
        self.assertEqual([c["object_name"] for c in clean], ["瓷砖"])
        self.assertIn("dependency", str(excluded))

    def test_source_overlap_blocks_rewritten_core_without_any_literal_term(self):
        text = "这里的施工动作无法判断。"
        payload = self.payload("施工前需要刷胶浆。", "施工动作", [1, 1])
        payload["ambiguities"] = [{**self.issue(), "blocked_terms": []}]
        clean, _, excluded = self.run_payload(payload, text)
        self.assertFalse(clean)
        self.assertIn("dependency", str(excluded))

    def test_ambiguous_optional_reason_is_pruned_without_losing_independent_core(self):
        text = "这里说一定要胶浆。不胶浆就容易空鼓。施工前应检查线路。"
        payload = self.payload("施工开始前应当检查线路。", "检查线路", [3, 3])
        payload["claims"][0]["reason"] = ["为了避免空鼓。", 2, 2]
        payload["ambiguities"] = [self.issue()]
        clean, _, _ = self.run_payload(payload, text)
        self.assertEqual(len(clean), 1)
        self.assertEqual(clean[0]["original_reasons"], [])
        self.assertEqual(clean[0]["source_quotes"], ["施工前应检查线路。"])
        server.claim_contract.validate_stored_evidence(clean[0], text)

    def test_paraphrase_is_allowed_but_does_not_mark_old_deletion_strategy(self):
        text = "施工前应检查线路。"
        payload = self.payload("施工开始前应当检查线路。", "检查线路", [1, 1])
        before = copy.deepcopy(payload)
        normalized = server.claim_wire.normalize(payload, text)
        self.assertNotIn("source_text_mode", normalized["claims"][0])
        self.assertEqual(payload, before)
        clean, dropped, _ = self.run_payload(payload, text)
        self.assertEqual(len(clean), 1, dropped)

    def test_title_cannot_guess_action_or_use_words_elsewhere_in_transcript(self):
        text = "低楼层的话，我还建你仙丹。另一个步骤是先装纱窗。"
        for title in ("低楼层先装纱窗", "先装纱窗", "施工建议"):
            with self.subTest(title=title):
                clean, _, excluded = self.run_payload(self.payload("此处动作不明。", title, [1, 2]), text)
                self.assertFalse(clean)
                self.assertIn("unsupported_source_title", str(excluded))

    def test_literal_action_must_not_lose_its_negation(self):
        text = "不要拆除承重墙体。"
        clean, _, excluded = self.run_payload(self.payload("拆除承重墙体。", "承重墙体", [1, 1]), text)
        self.assertFalse(clean)
        self.assertIn("source_negation_removed", str(excluded))

    def test_literal_title_does_not_prove_that_source_words_are_clear(self):
        text = "直接用瓷砖做泥包贴。"
        self.assertTrue(server.claim_contract.literal_title_supported("做泥包贴", text))
        # Detection still requires same-pass ambiguity identification, not copying alone.
        payload = self.payload(text, "做泥包贴", [1, 1])
        payload["ambiguities"] = [{**self.issue(), "blocked_terms": ["做泥包贴"]}]
        self.assertFalse(self.run_payload(payload, text)[0])

    def test_optional_triples_are_strict_not_silently_wrapped_or_repaired(self):
        text = "施工前应检查线路。"
        for field in ("reason", "alternative"):
            for invalid in ([], [["检查线路", 1, 1]], {"text": "检查线路", "span": [1, 1]}):
                payload = self.payload(text, "检查线路", [1, 1])
                payload["claims"][0][field] = invalid
                with self.subTest(field=field, invalid=invalid), self.assertRaisesRegex(ValueError, "invalid_evidence_pair"):
                    self.run_payload(payload, text)
        payload = self.payload(text, "检查线路", [1, 1])
        payload["claims"][0]["reasons"] = []
        with self.assertRaisesRegex(ValueError, "mixed_extraction_contract"):
            self.run_payload(payload, text)

    def test_v17_history_keeps_fine_segmentation_and_deletion_flag(self):
        text = "先做某个不明动作，施工前应检查线路。"
        payload = self.payload("施工前应检查线路。", "检查线路", [2, 2])
        payload["extraction_contract"] = "v17"
        claim = payload["claims"][0]
        claim.pop("reason")
        claim.pop("alternative")
        claim.update(reasons=[], alternatives=[])
        result = server.claim_wire.normalize_historical(payload, text)["claims"][0]
        self.assertEqual(result["source_quotes"], ["施工前应检查线路。"])
        self.assertEqual(result["source_text_mode"], "deletion_only")
        self.assertNotIn("source_title_mode", result)
        with self.assertRaisesRegex(ValueError, "missing_extraction_contract_v18"):
            self.run_payload(payload, text)

    def test_complete_budget_scheme_is_not_forced_into_fragments(self):
        text = "装修预算分四份，人工占25%，辅料占25%，主材占25%，定制占25%。"
        payload = self.payload("装修预算分四份，人工、辅料、主材和定制各占25%。", "装修预算", [1, 5])
        clean, dropped, _ = self.run_payload(payload, text)
        self.assertEqual(len(clean), 1, dropped)

    def test_literal_price_title_cannot_hide_cabinet_size_scope(self):
        text = "地柜五米，吊柜三米。台面加多层实木柜体，包安装一共六千元。"
        payload = self.payload("包安装一共六千元。", "包安装", [3, 4])
        clean, _, excluded = self.run_payload(payload, text)
        self.assertFalse(clean)
        self.assertIn("quotation_size_scope_not_preserved", str(excluded))
        payload["claims"][0]["condition"] = ["地柜五米，吊柜三米", 1, 2]
        clean, dropped, _ = self.run_payload(payload, text)
        self.assertEqual(len(clean), 1, dropped)


if __name__ == "__main__":
    unittest.main()
