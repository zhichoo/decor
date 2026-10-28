"""Soft-ad classification and automatic extraction safety; no upstream requests."""
import json
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
import advertising
import test_pipeline_safety as pipeline


class AdvertisingTests(unittest.TestCase):
    def setUp(self):
        self.video = {"title": "厨房装修", "transcript_text": "先把橱柜规划好。接着推荐这台冰箱。它的双循环和保鲜功能很好。"}

    def classify(self, decision="advertising", evidence=None):
        result = {"decision": decision, "reason": "科普铺垫后转向产品推介",
                  "evidence": evidence if evidence is not None else ["接着推荐这台冰箱", "它的双循环和保鲜功能很好"]}
        return advertising.classify(self.video, Mock(return_value=(json.dumps(result), None)), json.loads)

    def test_grounded_advertising_is_accepted(self):
        result = self.classify()
        self.assertEqual(result["decision"], "advertising")
        self.assertEqual(advertising.current_review(self.video | {"ad_review": result}), result)

    def test_fabricated_evidence_is_not_a_confirmed_ad(self):
        self.assertEqual(self.classify(evidence=["立即购买", "全网最低"])["decision"], "uncertain")

    def test_ad_requires_distinct_quotes(self):
        self.assertEqual(self.classify(evidence=["这台冰箱", "这台冰箱"])["decision"], "uncertain")

    def test_title_only_is_not_sent_to_model(self):
        call = Mock(side_effect=AssertionError("no model call"))
        result = advertising.classify({"title": "品牌推广", "transcript_text": "品牌推广"}, call, json.loads)
        self.assertEqual(result["decision"], "uncertain")

    def test_failure_does_not_default_to_not_ad(self):
        result = advertising.classify(self.video, Mock(return_value=(None, "timeout")), json.loads)
        self.assertEqual(result["decision"], "error")

    def test_invalid_json_is_held_for_review(self):
        result = advertising.classify(self.video, Mock(return_value=("invalid", None)), json.loads)
        self.assertEqual(result["decision"], "uncertain")

    def test_text_or_title_change_invalidates_review(self):
        video = self.video | {"ad_review": self.classify()}
        for key in ("title", "transcript_text"):
            self.assertEqual(advertising.current_review(video | {key: "修改后的内容"}), {})

    def test_prompt_distinguishes_soft_ads_from_brand_mentions(self):
        prompt = advertising.build_prompt(self.video)
        for phrase in ("后半段", "故事", "不因提到品牌", "ASR", "不是简单关键词"):
            self.assertIn(phrase, prompt)

    def test_manual_override_survives_input_changes(self):
        for decision in ("advertising", "not_ad", "uncertain"):
            video = self.video | {"ad_review": self.classify(), "ad_review_override": {"decision": decision}}
            effective = advertising.current_review(video | {"title": "changed", "transcript_text": ""})
            self.assertEqual(effective, {"decision": decision, "source": "manual"})


class AdvertisingDatabaseTests(unittest.TestCase):
    setUpClass = classmethod(pipeline.PipelineSafetyTests.setUpClass.__func__)
    tearDownClass = classmethod(pipeline.PipelineSafetyTests.tearDownClass.__func__)
    video = pipeline.PipelineSafetyTests.video
    claims = pipeline.PipelineSafetyTests.claims
    active = pipeline.PipelineSafetyTests.active

    def setUp(self):
        self.real_review = self.server.review_video_advertising
        pipeline.PipelineSafetyTests.setUp(self)

    def test_ads_uncertain_and_errors_never_extract_or_remove_existing_cards(self):
        for decision in ("advertising", "uncertain", "error"):
            with self.subTest(decision=decision), \
                 patch.object(self.server, "review_video_advertising", return_value={"decision": decision}), \
                 patch.object(self.server, "call_deepseek") as model:
                with self.server.connect() as conn:
                    result = self.server.extract_claims_for_video(conn, self.server.row_to_video(self.video()), automatic=True)
                self.assertEqual(result["status"], "skipped_advertising")
                model.assert_not_called()
                self.assertEqual([r["id"] for r in self.active()], ["old"])

    def test_manual_status_syncs_summary_cards_and_restores_auto(self):
        with self.server.connect() as conn:
            auto = {"version": advertising.VERSION, "input_hash": advertising.input_hash(self.video()),
                    "decision": "not_ad"}
            conn.execute("UPDATE videos SET ad_review=%s", (self.server.Json(auto),))
            for decision in ("advertising", "uncertain", "not_ad"):
                row = self.server.set_video_promotion(conn, self.video_id, decision)
                self.assertEqual(self.server.row_to_video(row)["ad_review"]["source"], "manual")
                self.assertEqual(self.server.fetch_video_page(conn)["videos"][0]["ad_review"]["decision"], decision)
                self.assertEqual(self.server.fetch_knowledge_page(conn)["claims"][0]["source_video_is_promotional"], decision == "advertising")
                with patch.object(self.server, "call_deepseek") as model:
                    self.assertEqual(self.real_review(conn, self.video_id)["decision"], decision)
                    model.assert_not_called()
            restored = self.server.set_video_promotion(conn, self.video_id, "auto")
            self.assertIsNone(restored["ad_review_override"])
            self.assertEqual(advertising.current_review(restored), auto)
        self.assertEqual([r["id"] for r in self.active()], ["old"])

    def test_manual_override_with_no_transcript_and_invalid_update(self):
        with self.server.connect() as conn:
            self.server.set_video_promotion(conn, self.video_id, "advertising")
            conn.execute("UPDATE videos SET transcript_text=NULL, has_transcript=false, ad_review=NULL")
            with patch.object(self.server, "call_deepseek") as model:
                self.assertEqual(self.real_review(conn, self.video_id)["decision"], "advertising")
                model.assert_not_called()
            with self.assertRaises(ValueError):
                self.server.set_video_promotion(conn, self.video_id, "invalid")
            self.assertIsNone(self.server.set_video_promotion(conn, "missing", "not_ad"))
            conn.execute("UPDATE videos SET deleted_at=1")
            self.assertIsNone(self.server.set_video_promotion(conn, self.video_id, "not_ad"))

    def test_manual_override_controls_queue_and_progress(self):
        with self.server.connect() as conn:
            conn.execute("UPDATE claims SET deleted_at=1")
            conn.execute("UPDATE videos SET status='transcript_saved', ad_review=%s", (self.server.Json({"decision": "advertising"}),))
            for decision, progress in (("advertising", "已完成"), ("uncertain", "待确认"), ("not_ad", "待观点")):
                self.server.set_video_promotion(conn, self.video_id, decision)
                self.assertEqual(self.server.fetch_progress_summary(conn)[progress], 1)
                if decision != "not_ad":
                    with patch.object(self.server, "extract_claims_for_video") as extract:
                        result = self.server.process_pending_queue(conn, limit=3)
                        self.assertEqual(result["remaining"], 0)
                        extract.assert_not_called()

    def test_manual_change_during_automatic_review_wins(self):
        def respond(_prompt):
            with self.server.connect() as second:
                self.server.set_video_promotion(second, self.video_id, "advertising")
            return json.dumps({"choices": [{"message": {"content": json.dumps({
                "decision": "not_ad", "reason": "普通内容", "evidence": []})}}]}), None
        with patch.object(self.server, "call_deepseek", side_effect=respond):
            with self.server.connect() as conn:
                self.assertEqual(self.real_review(conn, self.video_id)["decision"], "advertising")

    def test_authenticated_promotion_endpoint(self):
        server = self.server

        class QuietHandler(server.AppHandler):
            def log_message(self, _format, *args):
                pass

        httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), QuietHandler)
        worker = threading.Thread(target=httpd.serve_forever, daemon=True)
        worker.start()
        try:
            with patch.object(server, "ADMIN_PASSWORD", "test-only"), patch.dict(server.DB_STATUS, {"available": True}):
                for video_id, decision, expected in ((self.video_id, "advertising", 200),
                        (self.video_id, "invalid", 400), ("missing", "not_ad", 404), (self.video_id, "auto", 200)):
                    request = urllib.request.Request(
                        f"http://127.0.0.1:{httpd.server_port}/api/videos/{video_id}/promotion",
                        data=json.dumps({"decision": decision}).encode(),
                        headers={"Content-Type": "application/json", "Cookie": f"{server.ADMIN_SESSION_COOKIE}={server.make_admin_session_value()}"})
                    try:
                        response = urllib.request.urlopen(request, timeout=3)
                    except urllib.error.HTTPError as exc:
                        response = exc
                    with response:
                        self.assertEqual(response.status, expected)
                        result = json.load(response)
                        if decision == "advertising":
                            self.assertEqual(result["video"]["ad_review"]["source"], "manual")
                self.assertEqual([r["id"] for r in self.active()], ["old"])
        finally:
            httpd.shutdown()
            httpd.server_close()
            worker.join(timeout=2)

    def test_manual_extraction_is_still_available(self):
        with patch.object(self.server, "extract_claims_for_video_locked", return_value={"status": "completed"}) as extract:
            with self.server.connect() as conn:
                self.server.extract_claims_for_video(conn, self.server.row_to_video(self.video()))
            extract.assert_called_once()
            self.server.review_video_advertising.assert_not_called()

    def test_non_advertising_allows_automatic_extraction(self):
        with patch.object(self.server, "extract_claims_for_video_locked", return_value={"status": "completed"}) as extract:
            with self.server.connect() as conn:
                result = self.server.extract_claims_for_video(conn, self.server.row_to_video(self.video()), automatic=True)
            self.assertEqual(result["status"], "completed")
            extract.assert_called_once()

    def test_queue_does_not_repeatedly_process_advertisements(self):
        with self.server.connect() as conn:
            conn.execute("UPDATE claims SET deleted_at=1")
            conn.execute("UPDATE videos SET status='transcript_saved', ad_review=%s", (self.server.Json({"decision": "advertising"}),))
            with patch.object(self.server, "extract_claims_for_video") as extract:
                result = self.server.process_pending_queue(conn, limit=3)
                self.assertEqual(result["remaining"], 0)
                self.assertEqual(result["processed"], [])
                extract.assert_not_called()

    def test_missing_text_is_not_classified(self):
        with self.server.connect() as conn:
            conn.execute("UPDATE videos SET transcript_text=NULL,has_transcript=false,transcript_length=0")
            with patch.object(self.server, "call_deepseek") as model:
                self.assertEqual(self.real_review(conn, self.video_id)["decision"], "pending")
                model.assert_not_called()
            self.assertIsNone(self.video()["ad_review"])

    def test_classification_service_error_preserves_saved_text_and_cards(self):
        before = self.video()
        with patch.object(self.server, "review_video_advertising", side_effect=self.real_review), \
             patch.object(self.server, "call_deepseek", return_value=(None, "timeout")), \
             patch.object(self.server, "extract_claims_for_video_locked") as extract:
            with self.server.connect() as conn:
                video, _ = self.server.save_transcript_for_video(conn, before)
            self.assertEqual(video["transcript_text"], before["transcript_text"])
            self.assertEqual(video["ad_review"]["decision"], "error")
            extract.assert_not_called()
        self.assertEqual([r["id"] for r in self.active()], ["old"])

    def test_review_is_persisted_cached_and_returned_in_summaries(self):
        result = {"decision": "advertising", "reason": "测试推广", "evidence": ["旧文案", "装修验收"]}
        response = json.dumps({"choices": [{"message": {"content": json.dumps(result)}}]})
        with patch.object(self.server, "call_deepseek", return_value=(response, None)) as model:
            with self.server.connect() as conn:
                review = self.real_review(conn, self.video_id)
                self.assertEqual(review["decision"], "advertising")
                self.assertEqual(self.real_review(conn, self.video_id), review)
                self.assertEqual(conn.execute("SELECT ad_review FROM videos").fetchone()["ad_review"], review)
                page = self.server.fetch_video_page(conn)
                self.assertEqual(page["videos"][0]["ad_review"], review)
                self.assertNotIn("transcript_text", page["videos"][0])
                self.assertEqual(self.server.fetch_progress_summary(conn)["已完成"], 1)
            self.assertEqual(model.call_count, 1)
        self.assertEqual([r["id"] for r in self.active()], ["old"])

    def test_edit_during_review_does_not_save_stale_label(self):
        def respond(_prompt):
            with self.server.connect() as second:
                second.execute("UPDATE videos SET transcript_text = '人工新文案' WHERE id = %s", (self.video_id,))
            return json.dumps({"choices": [{"message": {"content": json.dumps({
                "decision": "not_ad", "reason": "普通科普", "evidence": []})}}]}), None
        with patch.object(self.server, "call_deepseek", side_effect=respond):
            with self.server.connect() as conn:
                self.assertEqual(self.real_review(conn, self.video_id)["decision"], "uncertain")
        self.assertIsNone(self.video()["ad_review"])

    def test_knowledge_and_video_detail_claims_inherit_source_promotion(self):
        review = {"version": advertising.VERSION, "input_hash": advertising.input_hash(self.video()),
                  "decision": "advertising", "reason": "产品推广"}
        with self.server.connect() as conn:
            conn.execute("UPDATE videos SET ad_review=%s", (self.server.Json(review),))
            page = self.server.fetch_knowledge_page(conn)
            self.assertTrue(page["claims"][0]["source_video_is_promotional"])
            source = self.video()
            claim = conn.execute("SELECT * FROM claims WHERE id='old'").fetchone()
            self.assertTrue(self.server.row_to_claim(claim, source_video=source)["source_video_is_promotional"])
            # Keeping cards when deleting a source must not discard its warning.
            self.server.delete_video_and_claims(conn, self.video_id, 100, "test", delete_claims=False)
            self.assertTrue(self.server.fetch_knowledge_page(conn)["claims"][0]["source_video_is_promotional"])

    def test_non_promotional_or_stale_source_review_has_no_claim_warning(self):
        for decision in ("not_ad", "uncertain", "advertising"):
            with self.subTest(decision=decision), self.server.connect() as conn:
                review = {"version": advertising.VERSION, "input_hash": advertising.input_hash(self.video()),
                          "decision": decision}
                if decision == "advertising":
                    review["input_hash"] = "outdated"
                conn.execute("UPDATE videos SET ad_review=%s", (self.server.Json(review),))
                self.assertFalse(self.server.fetch_knowledge_page(conn)["claims"][0]["source_video_is_promotional"])


if __name__ == "__main__":
    unittest.main()
