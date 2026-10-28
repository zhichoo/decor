"""Knowledge facets regressions in a private PostgreSQL schema, always rolled back.

Run with: .venv/bin/python -m unittest discover -s tests -p test_knowledge_facets.py -v
"""
import importlib.util
import json
import os
from collections import Counter
from contextlib import nullcontext
from pathlib import Path
import shlex
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from urllib.parse import urlencode, urlparse
import uuid

import psycopg2
from psycopg2 import sql
from psycopg2.extensions import make_dsn
from psycopg2.extras import RealDictCursor

ROOT = Path(__file__).resolve().parents[1]


class TestConnection:
    """Keep application queries inside the test's single rollback transaction."""

    def __init__(self, raw):
        self.raw = raw

    def execute(self, statement, params=None):
        cursor = self.raw.cursor()
        cursor.execute(statement, params)
        return cursor


class KnowledgeFacetsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        values = {}
        env_path = ROOT / ".env"
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                key, separator, value = line.removeprefix("export ").partition("=")
                if separator and not key.strip().startswith("#"):
                    tokens = shlex.split(value, comments=True)
                    values[key.strip()] = tokens[0] if tokens else ""
        cls.dsn = values.get("DATABASE_URL")
        if not cls.dsn and values.get("POSTGRES_PASSWORD"):
            cls.dsn = make_dsn(
                host="127.0.0.1", port=values.get("DECOR_DB_PORT", "15439"),
                dbname="decor", user="decor", password=values["POSTGRES_PASSWORD"],
                sslmode="disable", connect_timeout=5,
            )
        if not cls.dsn:
            raise unittest.SkipTest("Local .env database configuration is required")
        with patch.dict(os.environ, {"DATABASE_URL": cls.dsn}):
            spec = importlib.util.spec_from_file_location(
                "decor_knowledge_facets_test_server", ROOT / "backend/server.py"
            )
            cls.server = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(cls.server)

    def setUp(self):
        try:
            raw = psycopg2.connect(self.dsn, cursor_factory=RealDictCursor, connect_timeout=5)
        except psycopg2.Error:
            raise RuntimeError("Local PostgreSQL test connection failed") from None
        self.addCleanup(raw.close)
        self.addCleanup(raw.rollback)
        self.conn = TestConnection(raw)
        identifier = sql.Identifier("test_knowledge_facets_" + uuid.uuid4().hex)
        self.conn.execute(sql.SQL("CREATE SCHEMA {}").format(identifier))
        # No public fallback: all application SQL is restricted to the disposable schema.
        self.conn.execute(sql.SQL("SET LOCAL search_path TO {}").format(identifier))
        baseline = "\n".join(
            line for line in (ROOT / "db/schema.sql").read_text().splitlines()
            if not line.startswith(("CREATE EXTENSION ", "CREATE INDEX "))
        )
        self.conn.execute(baseline.replace("public.", identifier.as_string(raw) + "."))
        self.conn.execute(
            """INSERT INTO videos (id, platform, creator, title, source_url, created_at, updated_at)
               VALUES ('video', 'test', 'test', 'test', 'https://example.invalid/video', 1, 1),
                      ('deleted-video', 'test', 'test', 'test', 'https://example.invalid/deleted', 1, 1)"""
        )
        self.conn.execute("UPDATE videos SET deleted_at = 10 WHERE id = 'deleted-video'")
        self.cards = []
        for index in range(60):
            self.add_claim(f"base-{index:02}", "水电阶段", "明确推荐", ["厨房"], ["材料"], "基准观点")
        self.add_claim("overlap", "防水阶段", "明确不推荐", ["卫生间", "卫生间"],
                       ["卫生间", "避坑"], "交叠标签")
        self.add_claim("stage-only", "入住验收", "价格建议", [], [], "仅阶段命中")
        self.add_claim("stage-and-tag", "灯具开关五金", "有条件", [], ["五金"], "阶段标签同时命中")
        self.add_claim("multi-stage-tags", "家电家具软装", "未明确", [], [], "阶段包含多个标签")
        # The specified active-library definition depends only on claims.deleted_at.
        self.add_claim("active-on-deleted-video", "准备阶段", "明确推荐", None, None,
                       "仍有效的观点", video_id="deleted-video")
        self.add_claim("deleted", "木工阶段", "未明确", ["阳台"], ["预算"],
                       "已删除的观点", deleted_at=10)

    def add_claim(self, claim_id, stage, stance, spaces, topics, conclusion,
                  deleted_at=None, video_id="video"):
        self.cards.append({"id": claim_id, "stage": stage, "stance": stance,
                           "spaces": spaces or [], "topics": topics or [], "deleted_at": deleted_at})
        self.conn.execute(
            """INSERT INTO claims (id, video_id, object_name, stance, process_stage, space_tags,
                   topic_tags, original_conclusion, conditions, price_info, source_video_url,
                   created_at, deleted_at)
               VALUES (%s, %s, '测试对象', %s, %s, %s, %s, %s, '未提及', '未提及',
                       'https://example.invalid/video', %s, %s)""",
            (claim_id, video_id, stance, stage, json.dumps(spaces) if spaces is not None else None,
             json.dumps(topics) if topics is not None else None, conclusion, len(self.cards), deleted_at),
        )

    def expected_facets(self):
        active = [card for card in self.cards if card["deleted_at"] is None]
        return {
            "total": len(active),
            "stages": dict(Counter(card["stage"] for card in active)),
            "stances": dict(Counter(card["stance"] for card in active)),
            "tags": {
                tag: sum(tag in card["spaces"] or tag in card["topics"] or tag in card["stage"]
                         for card in active)
                for tag in set(self.server.TAGS["space_tags"] + self.server.TAGS["topic_tags"])
            },
        }

    def get_payload(self, path="/api/knowledge", **query):
        if query:
            path += "?" + urlencode(query)
        handler = SimpleNamespace(send_json=lambda payload: payload)
        with patch.object(self.server, "connect", side_effect=lambda: nullcontext(self.conn)), patch.dict(
            self.server.DB_STATUS, {"available": True, "message": "ok"}
        ):
            return self.server.AppHandler.handle_get(handler, urlparse(path))

    def test_global_counts_exceed_first_page_and_survive_pagination(self):
        first = self.get_payload()
        self.assertEqual(first["total"], 65)
        self.assertEqual(first["limit"], 50)
        self.assertEqual(len(first["claims"]), 50)
        self.assertTrue(first["has_more"])
        self.assertEqual(first["facets"], self.expected_facets())
        second = self.get_payload(offset=50)
        self.assertEqual(len(second["claims"]), 15)
        self.assertFalse(second["has_more"])
        self.assertEqual(second["facets"], first["facets"])
        self.assertEqual(len({card["id"] for card in first["claims"] + second["claims"]}), 65)
        beyond = self.get_payload(offset=1000)
        self.assertEqual(beyond["claims"], [])
        self.assertEqual(beyond["facets"], first["facets"])

    def test_all_categories_match_unsearched_api_totals(self):
        expected = self.expected_facets()
        for facet, parameter in (("stages", "stage"), ("stances", "stance"), ("tags", "tag")):
            for value, count in expected[facet].items():
                with self.subTest(parameter=parameter, value=value):
                    payload = self.get_payload(**{parameter: value, "limit": 1})
                    self.assertEqual(payload["total"], count)
                    self.assertEqual(payload["facets"], expected)
        group = self.get_payload(stages="水电阶段,防水阶段")
        self.assertEqual(group["total"], expected["stages"]["水电阶段"] + expected["stages"]["防水阶段"])
        self.assertEqual(group["facets"], expected)

    def test_search_and_combined_filters_never_restrict_facets(self):
        cases = [
            ({"stage": "水电阶段", "q": "基准"}, 60),
            ({"tag": "卫生间", "q": "交叠"}, 1),
            ({"stance": "明确推荐", "q": "不存在的搜索词"}, 0),
            ({"q": "仅阶段命中"}, 1),
            ({"stages": "水电阶段,防水阶段", "tag": "厨房", "stance": "明确推荐", "q": "基准"}, 60),
            ({"stage": "灯具开关五金", "tag": "五金", "stance": "有条件", "q": "同时"}, 1),
            ({"stage": "水电阶段", "tag": "厨房", "stance": "有条件"}, 0),
        ]
        for query, count in cases:
            with self.subTest(query=query):
                payload = self.get_payload(**query, limit=1)
                self.assertEqual(payload["total"], count)
                self.assertEqual(payload["facets"], self.expected_facets())

    def test_tag_union_deduplicates_and_matches_stage_substrings(self):
        facets = self.server.fetch_knowledge_facets(self.conn)
        self.assertEqual(facets["tags"]["卫生间"], 1)
        self.assertEqual(facets["tags"]["五金"], 1)
        for tag, claim_id in (("验收", "stage-only"), ("五金", "stage-and-tag"),
                              ("家电", "multi-stage-tags"), ("家具", "multi-stage-tags"),
                              ("软装", "multi-stage-tags")):
            with self.subTest(tag=tag):
                payload = self.get_payload(tag=tag)
                self.assertEqual(payload["total"], 1)
                self.assertEqual([card["id"] for card in payload["claims"]], [claim_id])
                self.assertEqual(facets["tags"][tag], 1)
        self.assertIs(type(facets["total"]), int)
        for key in ("stages", "stances", "tags"):
            self.assertTrue(all(type(count) is int for count in facets[key].values()))

    def test_explicit_stance_preserves_legacy_tag_stance(self):
        for stance in self.server.TAGS["stance"]:
            with self.subTest(stance=stance):
                explicit = self.get_payload(stance=stance)
                legacy = self.get_payload(tag=stance)
                self.assertEqual(explicit, legacy)
                self.assertTrue(all(card["stance"] == stance for card in explicit["claims"]))

    def test_soft_deleted_claim_is_excluded_from_every_count_and_search(self):
        facets = self.server.fetch_knowledge_facets(self.conn)
        self.assertEqual(facets, self.expected_facets())
        self.assertNotIn("木工阶段", facets["stages"])
        self.assertEqual(facets["tags"]["阳台"], 0)
        self.assertEqual(facets["tags"]["预算"], 0)
        self.assertEqual(self.get_payload(q="已删除")["total"], 0)
        self.assertEqual(self.get_payload(stage="木工阶段")["total"], 0)
        self.assertEqual(self.get_payload(tag="阳台")["total"], 0)
        self.assertEqual(facets["stances"]["未明确"], 1)
        self.assertEqual(self.get_payload(q="仍有效")["total"], 1)

    def test_bootstrap_keeps_cards_deferred_and_reuses_global_total(self):
        with patch.object(self.server, "BOOTSTRAP_CACHE", {"payload": None, "timestamp": 0}), patch.object(
            self.server, "fetch_knowledge_facets", wraps=self.server.fetch_knowledge_facets
        ) as fetch_facets:
            bootstrap = self.get_payload("/api/bootstrap")
            fetch_facets.assert_called_once_with(self.conn)
        knowledge = bootstrap["knowledge"]
        self.assertEqual(knowledge["claims"], [])
        self.assertIs(knowledge["deferred"], True)
        self.assertEqual(knowledge["facets"], self.expected_facets())
        self.assertEqual(bootstrap["stats"]["claim_count"], knowledge["facets"]["total"])
        self.assertEqual(bootstrap["stats"]["claim_count"], self.get_payload()["total"])

    def test_empty_library_has_zero_counts_and_keeps_all_tag_candidates(self):
        self.conn.execute("UPDATE claims SET deleted_at = 10")
        expected = {"total": 0, "stages": {}, "stances": {},
                    "tags": dict.fromkeys(self.expected_facets()["tags"], 0)}
        payload = self.get_payload()
        self.assertEqual(payload["facets"], expected)
        self.assertEqual(payload["total"], 0)
        self.assertEqual(payload["claims"], [])
        self.assertFalse(payload["has_more"])
        bootstrap = self.server.build_bootstrap_payload(self.conn)
        self.assertEqual(bootstrap["knowledge"]["facets"], expected)
        self.assertEqual(bootstrap["stats"]["claim_count"], 0)


if __name__ == "__main__":
    unittest.main()
