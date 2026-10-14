#!/usr/bin/env python3
"""Optional PostgreSQL demo data. Never initialize or overwrite existing rows."""
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import psycopg2
from psycopg2.extras import Json

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from init_db import LOCK_ID, SCHEMA_PATH, database_url, validate_schema

SOURCES = [
    {
        "id": "demo_src_kebadong",
        "platform": "douyin",
        "name": "磕巴东",
        "profile_url": "https://www.douyin.com/user/MS4wLjABAAAArlnxpsxwvsIFkIY2L0UqWPMCGmz6rWv0jURSFLDSreA",
        "priority": "P0",
        "status": "active",
        "notes": "用户确认的抖音装修账号，优先测试近一年公开视频。",
    },
    {
        "id": "demo_src_zhuangxiubang",
        "platform": "douyin,xiaohongshu",
        "name": "装修帮",
        "profile_url": "https://www.douyin.com/user/MS4wLjABAAAAVZlAt7qbW0bL3vKlpRn1t8TdNAySaWtoWpRiMLhlEdT2AO6P6L6LdoWtSR1Ajs6h",
        "priority": "P0",
        "status": "active",
        "notes": "测试来源，后续补充近一年公开视频链接。",
    },
    {
        "id": "demo_src_ashuang",
        "platform": "douyin,xiaohongshu",
        "name": "设计师阿爽",
        "profile_url": "https://www.douyin.com/user/MS4wLjABAAAAAUNPjSuAGItEmEFdrQ7_jyUakTH956APYHzMaZNE9ok",
        "priority": "P0",
        "status": "active",
        "notes": "测试来源，后续补充近一年公开视频链接。",
    },
    {
        "id": "demo_src_qiushu",
        "platform": "xiaohongshu",
        "name": "求叔（装修不求人）",
        "profile_url": "https://toobigdata.com/red/893504339/",
        "priority": "P0",
        "status": "active",
        "notes": "测试来源，需补充公开视频分享链接。",
    },
]

TRANSCRIPT = """不要脸的说，我装过的房子比你们刷过的视频都多，我敢说80%以上都在过度装修。你房子都是贷款买的，家里都挤挤巴巴的，你这不打肿脸充胖子吗？再说，你净装那些没有用的，用不了一年你就后悔了，它不实用呀。我做十几年装修了，我和我的亲戚朋友都说，不实用的东西都别做，咱们要把钱花在刀刃上呀。第1，墙面不要刷带颜色的乳胶漆，主要是带颜色的后期磕磕碰碰，谁也修复不了。你就留一矿泉水瓶，你不纯多余吗？修复出来和一个大补丁一样。更不要去考虑硅藻泥、艺术漆、贝壳粉，不但贵，还不环保，后期也修复不了。你想环保，就刷零花白乳胶漆，白色的是永远的经典。想要有点档次，就全屋都贴壁布，全屋五六千就够了，但是要三四个月之后再入住。第2，全屋定制不要省个一两千块钱儿，去本地的小工厂做柜子，大部分用的都是围边板。就是里边是建筑工地的支模板，四外边用的是好板子，你不割开看，你根本看不出来。你用这种板子做衣柜，甲醛能不超标吗？咱们就选3-4线品牌的全屋定制，和一线品牌的板材用的是一样的，就是花色不一样，但价格能便宜个1/3。第4，集成灶再喜欢也不要装，故障率不是一般的高呀，坏了的话都是不质保的零件儿。后期你搞卫生都是卫生死角，就选顶吸烟机加燃气灶，简单还不坏。第11，无主灯，真的适合小年轻的，40岁左右的就别装了。我家就是回家昏昏沉沉的，不亮，还是我家原来老房子就一个主灯，亮堂呀。为了面子装修就做无主灯，实用舒服，还得说是一个主灯，亮堂。"""

SHARE_TEXT = """0.23 bnQ:/ C@U.lP :4pm 07/25 入住一年就知道我说的对了# 装修最后悔的事 # 装修知识  https://v.douyin.com/Bf2zXdiISM8/ 复制此链接，打开Dou音搜索，直接观看视频！"""

VIDEOS = [
    {
        "id": "demo_vid_kebadong_001",
        "source_id": "demo_src_kebadong",
        "platform": "douyin",
        "creator": "磕巴东",
        "title": "入住一年就知道我说的对了",
        "source_url": "https://v.douyin.com/Bf2zXdiISM8/",
        "share_url": "https://v.douyin.com/Bf2zXdiISM8/",
        "share_text": SHARE_TEXT,
        "published_at": "2026",
        "transcript_text": TRANSCRIPT,
        "transcript_source": "TranscriptGenerate/manual",
        "status": "claims_extracted",
    }
]

CLAIMS = [
    {
        "id": "demo_claim_kbd_001",
        "video_id": "demo_vid_kebadong_001",
        "extraction_run_id": None,
        "object_name": "带颜色乳胶漆 / 硅藻泥 / 艺术漆 / 贝壳粉",
        "stance": "明确不推荐",
        "process_stage": "油工阶段",
        "space_tags": ["全屋"],
        "topic_tags": ["墙面", "材料", "环保", "避坑"],
        "original_conclusion": "墙面不要刷带颜色的乳胶漆，更不要去考虑硅藻泥、艺术漆、贝壳粉。",
        "original_reasons": ["带颜色后期磕碰修复不了", "硅藻泥、艺术漆、贝壳粉贵", "原文称不环保", "后期也修复不了"],
        "conditions": "壁布要三四个月之后再入住",
        "alternatives": ["零花白乳胶漆", "全屋壁布"],
        "price_info": "全屋壁布五六千",
        "source_video_url": "https://v.douyin.com/Bf2zXdiISM8/",
    },
    {
        "id": "demo_claim_kbd_002",
        "video_id": "demo_vid_kebadong_001",
        "extraction_run_id": None,
        "object_name": "本地小工厂全屋定制",
        "stance": "明确不推荐",
        "process_stage": "定制柜安装",
        "space_tags": ["全屋"],
        "topic_tags": ["全屋定制", "板材", "环保", "避坑"],
        "original_conclusion": "全屋定制不要省一两千去本地的小工厂做柜子。",
        "original_reasons": ["原文称大部分用围边板", "原文称甲醛可能超标"],
        "conditions": "未提及",
        "alternatives": ["3-4线品牌的全屋定制"],
        "price_info": "价格能便宜个1/3",
        "source_video_url": "https://v.douyin.com/Bf2zXdiISM8/",
    },
    {
        "id": "demo_claim_kbd_003",
        "video_id": "demo_vid_kebadong_001",
        "extraction_run_id": None,
        "object_name": "集成灶",
        "stance": "明确不推荐",
        "process_stage": "厨卫安装",
        "space_tags": ["厨房"],
        "topic_tags": ["厨电", "避坑", "维修", "卫生死角"],
        "original_conclusion": "集成灶再喜欢也不要装。",
        "original_reasons": ["故障率高", "坏了有不质保零件", "卫生死角"],
        "conditions": "未提及",
        "alternatives": ["顶吸烟机加燃气灶"],
        "price_info": "未提及",
        "source_video_url": "https://v.douyin.com/Bf2zXdiISM8/",
    },
    {
        "id": "demo_claim_kbd_004",
        "video_id": "demo_vid_kebadong_001",
        "extraction_run_id": None,
        "object_name": "无主灯",
        "stance": "有条件",
        "process_stage": "灯具开关五金",
        "space_tags": ["全屋"],
        "topic_tags": ["照明", "风格", "居住体验", "避坑"],
        "original_conclusion": "无主灯适合小年轻，40岁左右的就别装了。",
        "original_reasons": ["原文称不亮", "原文称主灯亮堂"],
        "conditions": "适合小年轻；40岁左右别装",
        "alternatives": ["一个主灯"],
        "price_info": "未提及",
        "source_video_url": "https://v.douyin.com/Bf2zXdiISM8/",
    },
]


def published_timestamp(value):
    """Year-only/unknown publication dates stay NULL, as in the backend."""
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    try:
        result = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return result if result.tzinfo else result.replace(tzinfo=timezone.utc)


def seed_data(dsn=None):
    now = int(time.time())
    inserted = {"sources": 0, "videos": 0, "claims": 0}
    skipped_videos = 0
    # Guard future edits too: this command may only write its demo namespace.
    for rows in (SOURCES, VIDEOS, CLAIMS):
        if any(not row["id"].startswith("demo_") for row in rows):
            raise RuntimeError("Seed IDs must use the demo_ prefix")
    if any(not row["source_id"].startswith("demo_") for row in VIDEOS):
        raise RuntimeError("Seed sources must use the demo_ prefix")
    if any(not row["video_id"].startswith("demo_") or row["extraction_run_id"] is not None
           for row in CLAIMS):
        raise RuntimeError("Seed claims may only reference demo videos, without extraction runs")
    conn = psycopg2.connect(dsn or database_url())
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("SET LOCAL search_path = ''")
                cur.execute("SELECT pg_advisory_xact_lock(%s)", (LOCK_ID,))
                validate_schema(cur, SCHEMA_PATH.read_text(encoding="utf-8"))
                for source in SOURCES:
                    cur.execute(
                        """
                        INSERT INTO public.sources
                          (id, platform, name, profile_url, priority, status, notes, created_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (id) DO NOTHING
                        """,
                        (source["id"], source["platform"], source["name"], source["profile_url"],
                         source["priority"], source["status"], source["notes"], now),
                    )
                    inserted["sources"] += cur.rowcount
                eligible_videos = set()
                for video in VIDEOS:
                    transcript = video.get("transcript_text") or ""
                    transcript_length = len(transcript.strip())
                    has_transcript = transcript_length > 0
                    cur.execute(
                        """
                        INSERT INTO public.videos (
                          id, source_id, platform, creator, title, source_url, published_at,
                          share_url, share_text, transcript_text, transcript_source,
                          transcript_created_at, has_transcript, transcript_length,
                          published_at_ts, status, created_at, updated_at
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s,
                                  %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT DO NOTHING
                        """,
                        (video["id"], video["source_id"], video["platform"], video["creator"],
                         video["title"], video["source_url"], video.get("published_at"),
                         video.get("share_url"), video.get("share_text"), transcript,
                         video.get("transcript_source"), now if has_transcript else None,
                         has_transcript, transcript_length,
                         published_timestamp(video.get("published_at")), video["status"], now, now),
                    )
                    inserted["videos"] += cur.rowcount
                    # URL conflicts must never attach demo claims to a restored
                    # video (or to a mismatched demo ID). Lock the eligible row
                    # against deletion or URL/source edits for this transaction.
                    cur.execute(
                        """SELECT id FROM public.videos
                           WHERE id = %s AND source_url = %s AND source_id = %s
                             AND deleted_at IS NULL FOR UPDATE""",
                        (video["id"], video["source_url"], video["source_id"]),
                    )
                    if cur.fetchone():
                        eligible_videos.add(video["id"])
                    else:
                        skipped_videos += 1
                for claim in CLAIMS:
                    if claim["video_id"] not in eligible_videos:
                        continue
                    cur.execute(
                        """
                        INSERT INTO public.claims (
                          id, video_id, extraction_run_id, object_name, stance, process_stage,
                          space_tags, topic_tags, original_conclusion, original_reasons,
                          conditions, alternatives, price_info, source_video_url, created_at
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (id) DO NOTHING
                        """,
                        (claim["id"], claim["video_id"], claim["extraction_run_id"],
                         claim["object_name"], claim["stance"], claim["process_stage"],
                         Json(claim["space_tags"]), Json(claim["topic_tags"]),
                         claim["original_conclusion"], Json(claim["original_reasons"]),
                         claim["conditions"], Json(claim["alternatives"]), claim["price_info"],
                         claim["source_video_url"], now),
                    )
                    inserted["claims"] += cur.rowcount
        return inserted, skipped_videos
    finally:
        conn.close()


def main():
    try:
        inserted, skipped = seed_data()
    except (RuntimeError, ValueError, OSError, psycopg2.Error) as exc:
        message = str(exc) if not isinstance(exc, psycopg2.Error) else "PostgreSQL seed failed (SQLSTATE: " + (exc.pgcode or "connection error") + ")"
        print(message, file=sys.stderr)
        return 1
    print("Demo rows inserted: " + ", ".join(f"{table}={count}" for table, count in inserted.items())
          + f"; conflicting/deleted videos skipped={skipped}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
