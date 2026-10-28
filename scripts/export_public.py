#!/usr/bin/env python3
"""Build an allowlisted static snapshot using a read-only, consistent DB transaction."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import html
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile

import psycopg2
from psycopg2.extras import RealDictCursor

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "scripts"))
import advertising
from init_db import database_url

VIDEO_FIELDS = ("id", "source_id", "platform", "creator", "title", "published_at", "status",
                "created_at", "updated_at", "transcript_created_at")
CLAIM_FIELDS = ("id", "video_id", "object_name", "stance", "process_stage", "space_tags", "topic_tags",
                "original_conclusion", "original_reasons", "conditions", "alternatives", "price_info", "created_at")
SOURCE_FIELDS = ("id", "platform", "name", "status", "created_at")
PUBLIC_TAGS = ("厨房", "卫生间", "客厅", "卧室", "阳台", "全屋", "预算", "避坑", "环保", "材料",
               "品牌", "维修", "照明", "家电", "五金", "全屋定制", "家具", "软装", "厨电", "未提及")


def public_url(value):
    from urllib.parse import urlsplit, urlunsplit
    try:
        parts = urlsplit(str(value or ""))
        if parts.scheme not in ("http", "https") or not parts.hostname or parts.username or parts.password:
            return ""
        # Tracking parameters and signed media URLs are not part of the public snapshot.
        return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
    except ValueError:
        return ""


def progress_state(video):
    decision = (video.get("ad_review") or {}).get("decision")
    if decision == "advertising" or video["status"] == "claims_filtered":
        return "已完成"
    if decision in ("uncertain", "error"):
        return "待确认"
    if video["status"] == "transcript_failed" or video.get("last_error"):
        return "失败"
    if not video["source_url"]:
        return "缺链接"
    if video["claim_count"]:
        return "已完成"
    return "待观点" if video["has_transcript"] else "待文案"


def make_snapshot(source_rows, video_rows, claim_rows, published_at=None):
    active_videos = {row["id"]: row for row in video_rows if row.get("deleted_at") is None}
    active_claims = [row for row in claim_rows if row.get("deleted_at") is None and row["video_id"] in active_videos]
    claim_counts = Counter(row["video_id"] for row in active_claims)
    videos = []
    for row in active_videos.values():
        text = (row.get("transcript_text") or "").strip()
        review = advertising.current_review(row)
        item = {key: row.get(key) for key in VIDEO_FIELDS}
        item.update(source_url=public_url(row.get("source_url")), share_url=public_url(row.get("source_url")),
                    transcript_text=text, has_transcript=bool(text), transcript_length=len(text),
                    claim_count=claim_counts[row["id"]], ad_review={"decision": review["decision"]} if review else {})
        if row.get("last_error"):
            item["last_error"] = "后台处理尚未完成；公开预览仅支持浏览。"
        item["progress_state"] = progress_state(item)
        videos.append(item)
    # The input query provides PostgreSQL's timezone-aware publication order.
    claims = []
    for row in active_claims:
        video = active_videos[row["video_id"]]
        item = {key: row.get(key) for key in CLAIM_FIELDS}
        for field in ("space_tags", "topic_tags", "original_reasons", "alternatives"):
            item[field] = item[field] or []
        item.update(source_video_url=public_url(video.get("source_url")), video_title=video["title"],
                    creator=video["creator"], platform=video["platform"],
                    source_video_is_promotional=advertising.current_review(video).get("decision") == "advertising")
        claims.append(item)
    sources = []
    for row in source_rows:
        related = [video for video in videos if video["source_id"] == row["id"]]
        item = {key: row.get(key) for key in SOURCE_FIELDS}
        item.update(profile_url=public_url(row.get("profile_url")), video_count=len(related),
                    claim_count=sum(video["claim_count"] for video in related),
                    pending_count=sum(not video["has_transcript"] for video in related))
        sources.append(item)
    groups = Counter((video["platform"], video["creator"]) for video in videos)
    platforms = Counter(video["platform"] for video in videos if video["platform"])
    tags = sorted(set(PUBLIC_TAGS).union(*(set(c["space_tags"] + c["topic_tags"]) for c in claims)))
    knowledge_facets = {
        "total": len(claims), "stages": dict(Counter(c["process_stage"] for c in claims)),
        "stances": dict(Counter(c["stance"] for c in claims)),
        "tags": {tag: sum(tag in c["space_tags"] or tag in c["topic_tags"] or tag in (c["process_stage"] or "")
                          for c in claims) for tag in tags},
    }
    progress = {key: 0 for key in ("全部", "缺链接", "待文案", "待观点", "已完成", "失败", "待确认")}
    progress.update(Counter(video["progress_state"] for video in videos))
    progress["全部"] = len(videos)
    return {
        "format_version": 1, "published_at": published_at or datetime.now(timezone.utc).isoformat(),
        "sources": sources, "videos": videos, "claims": claims,
        "stats": {"source_count": len(sources), "video_count": len(videos), "claim_count": len(claims),
                  "transcript_count": sum(video["has_transcript"] for video in videos)},
        "video_facets": {"total": len(videos),
                         "platforms": [{"platform": key, "video_count": value} for key, value in sorted(platforms.items())],
                         "creators": [{"platform": key[0], "creator": key[1], "video_count": value}
                                      for key, value in sorted(groups.items()) if key[1]]},
        "knowledge_facets": knowledge_facets, "progress_counts": progress,
    }


def read_snapshot():
    with psycopg2.connect(database_url(), cursor_factory=RealDictCursor) as conn:
        conn.set_session(readonly=True, isolation_level="REPEATABLE READ")
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM sources ORDER BY created_at DESC, id")
            sources = cursor.fetchall()
            cursor.execute("SELECT * FROM videos WHERE deleted_at IS NULL "
                           "ORDER BY published_at_ts DESC NULLS LAST, created_at DESC, id DESC")
            videos = cursor.fetchall()
            cursor.execute("SELECT c.* FROM claims c JOIN videos v ON v.id=c.video_id "
                           "WHERE c.deleted_at IS NULL AND v.deleted_at IS NULL ORDER BY c.created_at DESC, c.id DESC")
            claims = cursor.fetchall()
    return make_snapshot(sources, videos, claims)


class PublicHTML(HTMLParser):
    """Remove management nodes from the artifact, rather than merely hiding them."""
    void = frozenset("area base br col embed hr img input link meta param source track wbr".split())
    private_ids = frozenset(("admin-panel", "admin-login-modal", "video-delete-dialog", "promotion-form",
                             "transcript-edit-form", "transcript-edit-message", "detail-extract-message",
                             "settings-view", "deleted-view"))

    def __init__(self, published_at):
        super().__init__(convert_charrefs=False)
        self.parts = []
        self.depth = 0
        self.published_at = published_at

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if self.depth:
            if tag not in self.void:
                self.depth += 1
            return
        if attributes.get("id") == "admin-panel":
            self.parts.append('<div class="public-snapshot-note"><strong>公开预览 · 仅供浏览</strong>'
                              '<span>内容更新于 ' + html.escape(self.published_at[:10]) + '</span></div>')
        if (attributes.get("id") in self.private_ids or "data-admin-only" in attributes
                or "data-admin-required" in attributes or attributes.get("class") in
                ("transcript-actions", "detail-extract-actions")):
            self.depth = 0 if tag in self.void else 1
            return
        self.parts.append(self.get_starttag_text())

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in self.void:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if self.depth:
            self.depth -= 1
        else:
            self.parts.append(f"</{tag}>")

    def handle_data(self, data):
        if not self.depth:
            self.parts.append(data)

    def handle_entityref(self, name):
        self.handle_data(f"&{name};")

    def handle_charref(self, name):
        self.handle_data(f"&#{name};")

    def handle_decl(self, decl):
        self.handle_data(f"<!{decl}>")


def build_site(snapshot, output):
    output = Path(output).resolve()
    # Only replace a previous artifact created by this exporter, never an arbitrary directory.
    if output.exists() and not (output / ".decor-public-artifact").is_file():
        raise RuntimeError("Output directory already exists and is not a generated public artifact")
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(snapshot, ensure_ascii=False, separators=(",", ":"))
    version = hashlib.sha256(payload.encode()).hexdigest()[:16]
    with tempfile.TemporaryDirectory(prefix=".decor-public-build-", dir=output.parent) as directory:
        staging = Path(directory) / "site"
        staging.mkdir()
        (staging / "data").mkdir()
        (staging / "data" / f"library-{version}.json").write_text(payload, encoding="utf-8")
        for name in ("app.js", "styles.css", "public-client.js", "public.css"):
            shutil.copyfile(ROOT / "web" / name, staging / name)
        shutil.copytree(ROOT / "web/assets", staging / "assets")
        parser = PublicHTML(snapshot["published_at"])
        parser.feed((ROOT / "web/index.html").read_text(encoding="utf-8"))
        document = "".join(parser.parts)
        document = document.replace('<html lang="zh-CN">', '<html lang="zh-CN" data-public-snapshot="true">')
        document = document.replace("MVP Prototype", "Public Knowledge Library")
        document = document.replace("<title>装修知识库</title>", "<title>装修知识库 · 公开预览</title>")
        document = document.replace("</head>", '<link rel="stylesheet" href="./public.css?v=' + version + '" />\n  </head>')
        import re
        document = re.sub(r'(?<=styles\.css\?v=)[^" ]+', version, document)
        document = re.sub(r'<script src="\./app\.js[^\"]*"></script>',
                          f'<script src="./public-client.js?v={version}" data-snapshot="./data/library-{version}.json"></script>\n'
                          f'    <script src="./app.js?v={version}"></script>', document)
        if "data-snapshot=" not in document or parser.depth:
            raise RuntimeError("Static HTML generation failed")
        (staging / "index.html").write_text(document, encoding="utf-8")
        (staging / "404.html").write_text('<!doctype html><html lang="zh-CN"><meta charset="utf-8">'
                                          '<title>页面不存在</title><h1>页面不存在</h1>'
                                          '<p>公开预览不提供管理接口。</p><a href="/">返回知识库</a></html>', encoding="utf-8")
        (staging / "_headers").write_text(
            "/*\n  X-Content-Type-Options: nosniff\n  Referrer-Policy: strict-origin-when-cross-origin\n"
            "  X-Frame-Options: DENY\n  Cache-Control: no-cache\n"
            "  Content-Security-Policy: default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; connect-src 'self'; object-src 'none'; frame-src 'none'; "
            "base-uri 'none'; form-action 'none'; frame-ancestors 'none'\n", encoding="utf-8")
        (staging / "robots.txt").write_text("User-agent: *\nAllow: /\nDisallow: /data/\n", encoding="utf-8")
        (staging / ".decor-public-artifact").write_text(version, encoding="ascii")
        if output.exists():
            # This path is a known disposable build artifact, never a business-data directory.
            shutil.rmtree(output)
        os.replace(staging, output)
    return {"output": str(output), "version": version, **snapshot["stats"], "published_at": snapshot["published_at"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / ".runtime/public-site")
    args = parser.parse_args()
    try:
        result = build_site(read_snapshot(), args.output)
    except (psycopg2.Error, OSError, RuntimeError, ValueError):
        print("Public export failed; check database readiness and output path. No data was modified.", file=sys.stderr)
        raise SystemExit(1)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
