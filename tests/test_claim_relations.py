"""Real PostgreSQL pair lifecycle tests in disposable, isolated schemas."""
from pathlib import Path
import sys
from contextlib import nullcontext
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from urllib.parse import urlparse
import uuid

import psycopg2
from psycopg2 import sql
from psycopg2.extras import RealDictCursor

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
import server
import claim_relations as relations


class RelationContractTests(unittest.TestCase):
    def classify_equivalent(self, a, b, **overrides):
        result = {"id": "0", "kind": "equivalent", "reason": "均建议瓷砖留缝2毫米",
                  "a_quote": a["original_conclusion"], "b_quote": b["original_conclusion"],
                  "conditions_match": True, "scope_match": True, "numbers_match": True, **overrides}
        return relations.classify([(a, b)], lambda _: ({"pairs": [result]}, None), lambda raw: raw)[0]

    def test_same_claim_from_different_videos_is_equivalent(self):
        a = {"video_id": "v1", "original_conclusion": "瓷砖留缝2毫米。", "conditions": "未提及"}
        b = {"video_id": "v2", "original_conclusion": "瓷砖应留缝2毫米。", "conditions": "未提及"}
        self.assertEqual(self.classify_equivalent(a, b)["kind"], "equivalent")
        self.assertEqual(self.classify_equivalent(a, b, a_quote="原话没有的内容")["kind"], "distinct")
        self.assertEqual(self.classify_equivalent(a, b, conditions_match="true")["kind"], "distinct")

    def test_same_label_requires_matching_numbers_scope_conditions_and_stance(self):
        a = {"original_conclusion": "瓷砖留缝2毫米。", "conditions": "未提及", "source_scope": "general", "author_stance": "赞成"}
        for difference in ({"original_conclusion": "瓷砖留缝2.5毫米。"}, {"conditions": "仅限卫生间"},
                           {"source_scope": "personal"}, {"author_stance": "反对"}):
            with self.subTest(difference=difference):
                self.assertEqual(self.classify_equivalent(a, {**a, **difference})["kind"], "distinct")
        self.assertEqual(self.classify_equivalent({"original_conclusion": "自己装修三个月可装完"},
                                                  {"original_conclusion": "自己装修两个月可装完"})["kind"], "distinct")
        for key, av, bv in (("price_info", "2000元", "3000元"),
                            ("conditions", "层高2.7米以上", "层高2.5米以上")):
            with self.subTest(field=key):
                self.assertEqual(self.classify_equivalent({**a, key: av}, {**a, key: bv})["kind"], "distinct")

    def test_ambiguous_incomplete_or_repeated_model_output_is_rejected(self):
        pairs = [({}, {}), ({}, {})]
        for results in ([{"id": "0", "kind": "similar", "reason": "同一主张"}],
                        [{"id": "0", "kind": "similar", "reason": "同一主张"}] * 2,
                        [{"id": "0", "kind": "similar", "reason": ""}, {"id": "1", "kind": "distinct", "reason": "不同"}]):
            with self.subTest(results=results), self.assertRaises(ValueError):
                relations.classify(pairs, lambda _: ({"pairs": results}, None), lambda raw: raw)

    def test_unrelated_objects_are_not_retrieval_candidates(self):
        a = {"id": "a", "object_name": "底漆", "original_conclusion": "刷底漆"}
        b = {"id": "b", "object_name": "地轨门", "original_conclusion": "推荐地轨门"}
        self.assertEqual(relations.candidate_pairs([a, b]), [])

    def test_different_alternatives_or_missing_anchors_cannot_be_opposite(self):
        for a, b in (({"object_name": "风暖浴霸", "original_conclusion": "推荐风暖浴霸"},
                      {"object_name": "灯暖浴霸", "original_conclusion": "不推荐灯暖浴霸"}),
                     ({"object_name": "底漆", "original_conclusion": "刷底漆"},
                      {"object_name": "底漆", "original_conclusion": "不刷底漆"})):
            result = relations.classify([(a, b)], lambda _: ({"pairs": [{"id": "0", "kind": "opposite", "reason": "态度相反"}]}, None), lambda raw: raw)
            self.assertEqual(result[0]["kind"], "distinct")


class ClaimRelationsTests(unittest.TestCase):
    def setUp(self):
        if not server.PG_DSN:
            self.skipTest("Local database configuration required")
        self.raw = psycopg2.connect(server.PG_DSN, cursor_factory=RealDictCursor)
        self.conn = server.PGConnection(self.raw)
        self.schema = sql.Identifier("test_relations_" + uuid.uuid4().hex)
        self.conn.execute(sql.SQL("CREATE SCHEMA {}").format(self.schema))
        self.addCleanup(self.cleanup_schema)
        self.conn.execute(sql.SQL("SET search_path TO {}").format(self.schema))
        baseline = "\n".join(line for line in (ROOT / "db/schema.sql").read_text().splitlines()
                             if not line.startswith(("CREATE EXTENSION ", "CREATE INDEX ")))
        self.conn.execute(baseline.replace("public.", self.schema.as_string(self.raw) + "."))
        for index in range(3):
            self.conn.execute("""INSERT INTO videos (id, platform, creator, title, source_url, created_at, updated_at)
                VALUES (%s,'test',%s,%s,%s,1,1)""", (f"v{index}", f"作者{index}", f"视频{index}", f"https://example.invalid/{index}"))
        self.cards = [self.add_card("a", "v0", "不刷底漆"), self.add_card("b", "v1", "刷底漆"),
                      self.add_card("c", "v2", "底漆干透再刷面漆")]

    def cleanup_schema(self):
        self.raw.rollback()
        self.raw.autocommit = True
        self.conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(self.schema))
        self.raw.close()

    def add_card(self, card_id, video_id, conclusion):
        self.conn.execute("""INSERT INTO claims (id,video_id,object_name,stance,process_stage,
            original_conclusion,conditions,price_info,source_video_url,created_at)
            VALUES (%s,%s,'底漆','未明确','油工阶段',%s,'未提及','未提及','https://example.invalid/',1)""",
            (card_id, video_id, conclusion))
        return self.conn.execute("SELECT * FROM claims WHERE id=%s", (card_id,)).fetchone()

    def link(self, a=0, b=1, kind="opposite"):
        with self.conn.transaction():
            return relations.save_relation(self.conn, self.cards[a], self.cards[b], kind, "是否刷底漆的建议相反")

    def test_bidirectional_counts_and_lookup_are_independent_of_search_and_pagination(self):
        self.assertTrue(self.link())
        self.assertTrue(self.link(1, 2, "similar"))
        a = server.fetch_claim_relations(self.conn, "a")
        b = server.fetch_claim_relations(self.conn, "b")
        self.assertEqual(a["relations"][0]["claim"]["id"], "b")
        self.assertEqual(a["relations"][0]["claim"]["creator"], "作者1")
        self.assertEqual({row["claim"]["id"] for row in b["relations"]}, {"a", "c"})
        self.assertEqual(a["claim"]["relation_counts"], {"opposite": 1})
        # There is deliberately no transitive a-c relationship.
        self.assertEqual(len(a["relations"]), 1)
        filtered = server.fetch_knowledge_page(self.conn, {"q": ["不刷底漆"]}, limit=1)
        self.assertEqual(filtered["total"], 1)
        self.assertEqual(filtered["claims"][0]["relation_counts"], {"opposite": 1})

    def test_soft_delete_restore_purge_and_hard_delete_cascade(self):
        self.link()
        self.conn.execute("UPDATE claims SET deleted_at=10 WHERE id='b'")
        self.assertEqual(server.fetch_claim_relations(self.conn, "a")["relations"], [])
        self.assertIsNone(server.fetch_claim_relations(self.conn, "b"))
        self.conn.execute("UPDATE claims SET deleted_at=NULL WHERE id='b'")
        self.assertEqual(len(server.fetch_claim_relations(self.conn, "a")["relations"]), 1)
        self.conn.execute("UPDATE videos SET purged_at=10 WHERE id='v1'")
        self.assertEqual(server.fetch_claim_relations(self.conn, "a")["relations"], [])
        self.conn.execute("DELETE FROM claims WHERE id='b'")
        self.assertEqual(self.conn.execute("SELECT count(*) AS n FROM claim_relations").fetchone()["n"], 0)

    def test_changed_evidence_invalidates_relation_and_stale_model_cannot_restore_it(self):
        self.link()
        self.conn.execute("UPDATE claims SET conditions='潮湿墙面' WHERE id='b'")
        self.assertEqual(server.fetch_claim_relations(self.conn, "a")["relations"], [])
        self.assertFalse(self.link())
        self.assertEqual(relations.attach_counts(self.conn, [{"id": "a"}])[0]["relation_counts"], {})

    def test_canonical_upsert_and_distinct_are_hidden_without_deleting_cards(self):
        self.link()
        self.link(1, 0, "similar")
        self.assertEqual(len(server.fetch_claim_relations(self.conn, "a")["relations"]), 1)
        self.link(0, 1, "distinct")
        self.assertEqual(server.fetch_claim_relations(self.conn, "a")["relations"], [])
        self.assertEqual(self.conn.execute("SELECT count(*) AS n FROM claims").fetchone()["n"], 3)

    def test_same_claims_link_both_sources_without_replacing_cards(self):
        other = self.add_card("d", "v2", "不刷底漆")
        with self.conn.transaction():
            self.assertTrue(relations.save_relation(self.conn, self.cards[0], other, "equivalent", "都建议不刷底漆"))
        for card_id, related in (("a", "d"), ("d", "a")):
            payload = server.fetch_claim_relations(self.conn, card_id)
            self.assertEqual(payload["claim"]["relation_counts"], {"equivalent": 1})
            self.assertEqual(payload["relations"][0]["claim"]["id"], related)
            self.assertNotEqual(payload["claim"]["video_id"], payload["relations"][0]["claim"]["video_id"])
        self.assertEqual(self.conn.execute("SELECT count(*) AS n FROM claims WHERE deleted_at IS NULL").fetchone()["n"], 4)

    def test_upgrade_preserves_existing_links_and_is_repeatable(self):
        self.link()
        self.conn.execute("UPDATE claim_relations SET version=%s", (relations.LEGACY_VERSION,))
        self.conn.execute("ALTER TABLE claim_relations DROP CONSTRAINT claim_relations_kind_check")
        self.conn.execute("""ALTER TABLE claim_relations ADD CONSTRAINT claim_relations_kind_check
            CHECK (kind IN ('opposite','conditions','similar','distinct'))""")
        for _ in range(2):
            with self.conn.transaction():
                relations.migrate_schema(self.raw.cursor())
        self.assertEqual(len(server.fetch_claim_relations(self.conn, "a")["relations"]), 1)
        other = self.add_card("d", "v2", "不刷底漆")
        with self.conn.transaction():
            self.assertTrue(relations.save_relation(self.conn, self.cards[0], other, "equivalent", "都建议不刷底漆"))
        self.assertEqual(server.fetch_claim_relations(self.conn, "a")["claim"]["relation_counts"], {"opposite": 1, "equivalent": 1})

    def test_new_extraction_enqueues_cards_in_the_same_transaction(self):
        video = self.conn.execute("SELECT * FROM videos WHERE id='v0'").fetchone()
        claims = server.insert_claims(self.conn, video, None, [{"object_name": "测试", "original_conclusion": "测试观点"}])
        row = self.conn.execute("SELECT * FROM claim_relation_jobs WHERE claim_id=%s", (claims[0]["id"],)).fetchone()
        self.assertEqual(row["status"], "pending")
        self.assertEqual(self.conn.execute("SELECT deleted_at FROM claims WHERE id='a'").fetchone()["deleted_at"] is None, False)

    def test_read_only_api_allows_relations_and_returns_404_after_deletion(self):
        self.link()
        handler = SimpleNamespace(send_json=lambda payload: payload,
                                  send_error_json=lambda status, error: {"status": status})
        with patch.object(server, "connect", side_effect=lambda: nullcontext(self.conn)), \
                patch.object(server, "PUBLIC_READ_ONLY", True), patch.dict(server.DB_STATUS, {"available": True}):
            payload = server.AppHandler.handle_get(handler, urlparse("/api/knowledge/claims/a/relations"))
            self.assertEqual(payload["relations"][0]["claim"]["id"], "b")
            self.conn.execute("UPDATE claims SET deleted_at=10 WHERE id='a'")
            self.assertEqual(server.AppHandler.handle_get(handler, urlparse("/api/knowledge/claims/a/relations")), {"status": 404})

    def test_background_failure_is_durable_and_never_automatically_resubmitted(self):
        self.conn.execute("INSERT INTO claim_relation_jobs (claim_id,updated_at) VALUES ('a',1)")
        with patch.object(server, "connect", side_effect=lambda: nullcontext(self.conn)), \
                patch.object(relations, "refresh", side_effect=ValueError("model_failed")) as refresh, \
                patch.object(server.time, "sleep", side_effect=KeyboardInterrupt):
            for _ in range(2):
                with self.assertRaises(KeyboardInterrupt):
                    server.run_claim_relation_jobs()
            self.assertEqual(refresh.call_count, 1)
        self.assertEqual(self.conn.execute("SELECT status FROM claim_relation_jobs WHERE claim_id='a'").fetchone()["status"], "failed")
        self.assertEqual(self.conn.execute("SELECT count(*) AS n FROM claims WHERE deleted_at IS NULL").fetchone()["n"], 3)


if __name__ == "__main__":
    unittest.main()
