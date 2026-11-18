"""All-card audit is read-only and never treats missing evidence as a pass."""
import copy
import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import test_claim_safety as safety_tests

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("decor_check_claims", ROOT / "scripts/check_claims.py")
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)
server = safety_tests.server


class CheckClaimsTests(unittest.TestCase):
    def fixture(self, legacy=False, stored=False):
        text = "石膏板的厚度建议采用9毫米。"
        payload = safety_tests.ClaimSafetyTests().payload(text, "石膏板厚度建议采用9厘米。", object_name="石膏板厚度")
        candidate = server.claim_wire.normalize_legacy(payload, text)["claims"][0]
        claim = {**candidate, "id": "card", "video_id": "video", "extraction_run_id": "run", "deleted_at": None}
        if stored:
            claim["evidence_contract"] = server.claim_contract.VERSION
        else:
            for key in ("field_evidence", "source_scope", "scope_quote"):
                claim.pop(key, None)
        if legacy:
            payload = {"claims": [candidate]}
            for key in ("claim_id", "field_evidence", "source_scope", "scope_quote", "promotion_relation"):
                payload["claims"][0].pop(key)
            claim["source_quotes"] = []
        raw = {"choices": [{"message": {"content": json.dumps(payload)}}]}
        return {"sources": [], "claims": [claim], "videos": [{"id": "video", "title": "测试", "creator": "测试",
            "transcript_text": text, "deleted_at": None}], "extraction_runs": [{"id": "run", "prompt_version": "legacy" if legacy else "test",
            "video_id": "video", "input_hash": audit.text_hash(text), "raw_response_json": raw}]}

    def test_audit_detects_bound_unit_error_without_calls_or_input_mutation(self):
        snapshot = self.fixture()
        before = copy.deepcopy(snapshot)
        with patch.object(server, "call_deepseek") as model, patch.object(server, "connect") as connect:
            result = audit.check_snapshot(snapshot, server)
        model.assert_not_called()
        connect.assert_not_called()
        self.assertEqual(snapshot, before)
        self.assertEqual(result["summary"]["active_cards_checked"], 1)
        self.assertEqual(result["summary"]["finding_cards"], {"field_quantity_error": 1})

    def test_legacy_quotes_can_be_recovered_but_not_invented_as_field_bindings(self):
        result = audit.check_snapshot(self.fixture(legacy=True), server)
        record = result["cards"][0]
        self.assertEqual(record["status"], "insufficient_evidence")
        self.assertEqual(record["evidence_origin"], "matching_extraction_run")
        self.assertIn("missing_field_bindings", record["limitations"])
        self.assertIn("unbound_quantity_warning", str(record["warnings"]))
        self.assertFalse(record["findings"])

    def test_stale_run_cannot_supply_current_evidence(self):
        snapshot = self.fixture(legacy=True)
        snapshot["videos"][0]["transcript_text"] += "来源已经修正。"
        record = audit.check_snapshot(snapshot, server)["cards"][0]
        self.assertIn("source_changed_since_extraction", record["limitations"])
        self.assertNotIn("recovered_quote_count", record)

    def test_deleted_records_are_counted_but_not_resurrected_or_checked_as_active(self):
        snapshot = self.fixture()
        snapshot["claims"] += [{**snapshot["claims"][0], "id": "deleted", "deleted_at": 1},
                               {**snapshot["claims"][0], "id": "archived", "video_id": "archived-video"}]
        snapshot["videos"].append({"id": "archived-video", "deleted_at": 1})
        summary = audit.check_snapshot(snapshot, server)["summary"]
        self.assertEqual(summary["total_rows_checked"], 3)
        self.assertEqual(summary["active_cards_checked"], 1)
        self.assertEqual(summary["statuses"]["archived_deleted_card"], 1)
        self.assertEqual(summary["statuses"]["archived_deleted_video"], 1)

    def test_missing_quote_never_becomes_rule_pass(self):
        snapshot = self.fixture(legacy=True)
        snapshot["extraction_runs"][0]["raw_response_json"] = None
        record = audit.check_snapshot(snapshot, server)["cards"][0]
        self.assertEqual(record["status"], "insufficient_evidence")
        self.assertIn("condition_coverage_not_verifiable", record["limitations"])

    def test_bad_quote_type_is_a_finding_not_a_crash(self):
        snapshot = self.fixture()
        snapshot["claims"][0]["source_quotes"] = [42]
        record = audit.check_snapshot(snapshot, server)["cards"][0]
        self.assertIn("quote_not_in_current_transcript", str(record["findings"]))

    def test_stored_bindings_work_without_raw_model_response(self):
        snapshot = self.fixture(stored=True)
        snapshot["extraction_runs"][0]["raw_response_json"] = None
        record = audit.check_snapshot(snapshot, server)["cards"][0]
        self.assertEqual(record["evidence_origin"], "stored_card_bindings")
        self.assertEqual(record["evidence_contract"], server.claim_contract.VERSION)
        self.assertEqual(record["limitations"], [])
        self.assertIn("field_quantity_error", str(record["findings"]))

    def test_invalid_stored_binding_cannot_be_replaced_by_historical_response(self):
        snapshot = self.fixture(stored=True)
        snapshot["claims"][0]["field_evidence"]["original_conclusion"] = [42]
        record = audit.check_snapshot(snapshot, server)["cards"][0]
        self.assertIn("invalid_stored_evidence", str(record["findings"]))
        self.assertNotIn("evidence_origin", record)
        self.assertIn("missing_field_bindings", record["limitations"])

    def test_stored_binding_with_changed_or_wrong_video_lineage_is_not_used(self):
        for field, value in (("input_hash", "changed"), ("video_id", "another"), ("prompt_version", "")):
            snapshot = self.fixture(stored=True)
            snapshot["extraction_runs"][0][field] = value
            record = audit.check_snapshot(snapshot, server)["cards"][0]
            with self.subTest(field=field):
                self.assertNotIn("evidence_origin", record)
                self.assertEqual(record["status"], "insufficient_evidence")

    def test_stored_evidence_without_rule_findings_is_not_factual_verification(self):
        snapshot = self.fixture(stored=True)
        snapshot["claims"][0]["original_conclusion"] = "石膏板厚度建议采用9毫米。"
        record = audit.check_snapshot(snapshot, server)["cards"][0]
        self.assertEqual(record["status"], "no_rule_findings")
        self.assertEqual(record["evidence_origin"], "stored_card_bindings")

    def test_stored_bound_price_does_not_pass_with_omitted_subtotal_component(self):
        snapshot = self.fixture(stored=True)
        text = "灯具两千元，插座一千元，窗帘两千五百元，合计五千五百元。"
        snapshot["videos"][0]["transcript_text"] = text
        snapshot["extraction_runs"][0].update(input_hash=audit.text_hash(text), raw_response_json=None)
        snapshot["claims"][0].update(object_name="灯具窗帘预算", source_quotes=[text],
            original_conclusion="灯具两千元、窗帘两千五百元合计五千五百元。")
        record = audit.check_snapshot(snapshot, server)["cards"][0]
        self.assertIn("subtotal_scope_error", str(record["findings"]))
