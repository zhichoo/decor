#!/usr/bin/env python3
import json
import sqlite3
import time
from pathlib import Path

from server import DEFAULT_DB, init_db, json_dumps


DB_PATH = DEFAULT_DB
NOW = int(time.time())

SOURCES = [
    {
        "id": "src_kebadong",
        "platform": "douyin",
        "name": "磕巴东",
        "profile_url": "https://www.douyin.com/user/MS4wLjABAAAArlnxpsxwvsIFkIY2L0UqWPMCGmz6rWv0jURSFLDSreA",
        "priority": "P0",
        "status": "active",
        "notes": "用户确认的抖音装修账号，优先测试近一年公开视频。",
    },
    {
        "id": "src_zhuangxiubang",
        "platform": "douyin,xiaohongshu",
        "name": "装修帮",
        "profile_url": "https://www.douyin.com/user/MS4wLjABAAAAVZlAt7qbW0bL3vKlpRn1t8TdNAySaWtoWpRiMLhlEdT2AO6P6L6LdoWtSR1Ajs6h",
        "priority": "P0",
        "status": "active",
        "notes": "测试来源，后续补充近一年公开视频链接。",
    },
    {
        "id": "src_ashuang",
        "platform": "douyin,xiaohongshu",
        "name": "设计师阿爽",
        "profile_url": "https://www.douyin.com/user/MS4wLjABAAAAAUNPjSuAGItEmEFdrQ7_jyUakTH956APYHzMaZNE9ok",
        "priority": "P0",
        "status": "active",
        "notes": "测试来源，后续补充近一年公开视频链接。",
    },
    {
        "id": "src_qiushu",
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
        "id": "vid_kebadong_001",
        "source_id": "src_kebadong",
        "platform": "douyin",
        "creator": "磕巴东",
        "title": "入住一年就知道我说的对了",
        "source_url": "https://v.douyin.com/Bf2zXdiISM8/",
        "share_url": "https://v.douyin.com/Bf2zXdiISM8/",
        "share_text": SHARE_TEXT,
        "published_at": "2026",
        "transcript_text": TRANSCRIPT,
        "transcript_source": "TranscriptGenerate/manual",
        "status": "claims_seeded",
    }
]

CLAIMS = [
    {
        "id": "claim_kbd_001",
        "video_id": "vid_kebadong_001",
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
        "id": "claim_kbd_002",
        "video_id": "vid_kebadong_001",
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
        "id": "claim_kbd_003",
        "video_id": "vid_kebadong_001",
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
        "id": "claim_kbd_004",
        "video_id": "vid_kebadong_001",
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


def main():
    init_db()
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        for source in SOURCES:
            conn.execute(
                """
                INSERT INTO sources (id, platform, name, profile_url, priority, status, notes, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                  platform=excluded.platform,
                  name=excluded.name,
                  profile_url=excluded.profile_url,
                  priority=excluded.priority,
                  status=excluded.status,
                  notes=excluded.notes
                """,
                (
                    source["id"],
                    source["platform"],
                    source["name"],
                    source["profile_url"],
                    source["priority"],
                    source["status"],
                    source["notes"],
                    NOW,
                ),
            )
        for video in VIDEOS:
            conn.execute(
                """
                INSERT INTO videos (
                  id, source_id, platform, creator, title, source_url, published_at,
                  share_url, share_text,
                  transcript_text, transcript_source, transcript_created_at,
                  status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(source_url) DO UPDATE SET
                  share_url=excluded.share_url,
                  share_text=excluded.share_text,
                  transcript_text=excluded.transcript_text,
                  transcript_source=excluded.transcript_source,
                  transcript_created_at=excluded.transcript_created_at,
                  status=excluded.status,
                  updated_at=excluded.updated_at
                """,
                (
                    video["id"],
                    video["source_id"],
                    video["platform"],
                    video["creator"],
                    video["title"],
                    video["source_url"],
                    video["published_at"],
                    video.get("share_url"),
                    video.get("share_text"),
                    video["transcript_text"],
                    video["transcript_source"],
                    NOW,
                    video["status"],
                    NOW,
                    NOW,
                ),
            )
        for claim in CLAIMS:
            conn.execute(
                """
                INSERT INTO claims (
                  id, video_id, extraction_run_id, object_name, stance, process_stage,
                  space_tags, topic_tags, original_conclusion, original_reasons,
                  conditions, alternatives, price_info, source_video_url, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                  object_name=excluded.object_name,
                  stance=excluded.stance,
                  process_stage=excluded.process_stage,
                  space_tags=excluded.space_tags,
                  topic_tags=excluded.topic_tags,
                  original_conclusion=excluded.original_conclusion,
                  original_reasons=excluded.original_reasons,
                  conditions=excluded.conditions,
                  alternatives=excluded.alternatives,
                  price_info=excluded.price_info,
                  source_video_url=excluded.source_video_url
                """,
                (
                    claim["id"],
                    claim["video_id"],
                    claim["extraction_run_id"],
                    claim["object_name"],
                    claim["stance"],
                    claim["process_stage"],
                    json_dumps(claim["space_tags"]),
                    json_dumps(claim["topic_tags"]),
                    claim["original_conclusion"],
                    json_dumps(claim["original_reasons"]),
                    claim["conditions"],
                    json_dumps(claim["alternatives"]),
                    claim["price_info"],
                    claim["source_video_url"],
                    NOW,
                ),
            )
    print(f"Seeded {DB_PATH}")


if __name__ == "__main__":
    main()
