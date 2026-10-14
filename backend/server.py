#!/usr/bin/env python3
import hashlib
import hmac
import json
import os
import re
import secrets
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import urllib.error
import urllib.request
import uuid
from base64 import b64decode, b64encode
from contextlib import contextmanager
from datetime import datetime, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

import psycopg2
from psycopg2.extras import Json, RealDictCursor


ROOT = Path(__file__).resolve().parent
STATIC_ROOT = Path(os.environ["STATIC_ROOT"]).resolve() if os.environ.get("STATIC_ROOT") else None


def load_local_config():
    config_path = ROOT / "config.local.json"
    if not config_path.exists():
        return
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"Failed to load {config_path}: {exc}", file=sys.stderr)
        return
    for key, value in config.items():
        if value is None:
            continue
        os.environ.setdefault(str(key), str(value))


load_local_config()

PROMPT_VERSION = "extract_claims_v3"
DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-flash")
DEEPSEEK_BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_GROUP = os.environ.get("DEEPSEEK_GROUP", "").strip()
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "").strip()
ADMIN_SESSION_COOKIE = "decor_admin_session"
ADMIN_SESSION_MAX_AGE_SECONDS = int(os.environ.get("ADMIN_SESSION_MAX_AGE_SECONDS", str(7 * 24 * 60 * 60)))
MAX_ERROR_MESSAGE_LENGTH = 2000
MAX_TRANSCRIPT_DEBUG_LENGTH = 1500
TRANSCRIPT_API_BASE_URL = "https://www.transcriptgenerate.com/prod-api"
TRANSCRIPTGENERATE_TOKEN = os.environ.get("TRANSCRIPTGENERATE_TOKEN", "").strip()
TRANSCRIPTGENERATE_EMAIL = os.environ.get("TRANSCRIPTGENERATE_EMAIL", "").strip()
TRANSCRIPTGENERATE_PASSWORD = os.environ.get("TRANSCRIPTGENERATE_PASSWORD", "").strip()
TRANSCRIPT_ACCOUNTS_PATH = ROOT / "transcriptgenerate-accounts.local.json"
TRANSCRIPT_QUEUE_DELAY_SECONDS = float(os.environ.get("TRANSCRIPT_QUEUE_DELAY_SECONDS", "120"))
AUTO_QUEUE_BATCH_LIMIT = int(os.environ.get("AUTO_QUEUE_BATCH_LIMIT", "20"))
BOOTSTRAP_CACHE_TTL_SECONDS = float(os.environ.get("BOOTSTRAP_CACHE_TTL_SECONDS", "15"))
MIN_TRANSCRIPT_LENGTH = int(os.environ.get("MIN_TRANSCRIPT_LENGTH", "120"))
TRANSCRIPT_AES_KEY_HEX = "6161444a4c3264394466684c5a4f307a"
TRANSCRIPT_AES_IV_HEX = "34313241444453534641333432343432"
TRANSCRIPT_POLL_INTERVAL_SECONDS = 2
TRANSCRIPT_MAX_POLLS = 30
BOOTSTRAP_CACHE_LOCK = threading.RLock()
BOOTSTRAP_CACHE = {
    "timestamp": 0,
    "payload": None,
}
DEFAULT_VIDEO_LIMIT = 30
DEFAULT_KNOWLEDGE_LIMIT = 50
MAX_PAGE_LIMIT = 100
QUEUE_JOB_LOCK = threading.RLock()
QUEUE_JOB = {
    "job_id": None,
    "running": False,
    "logs": [],
    "processed": [],
    "failed": [],
    "remaining": None,
    "started_at": None,
    "finished_at": None,
    "cancel_requested": False,
}
VIDEO_PROCESS_LOCKS = {}
VIDEO_PROCESS_LOCKS_LOCK = threading.RLock()
DOUYIN_LOGIN_LOCK = threading.RLock()
DOUYIN_LOGIN_JOB = {
    "running": False,
    "status": "idle",
    "message": "未检查",
    "logged_in": False,
    "cookie_count": 0,
    "valid_cookie_names": [],
    "started_at": None,
    "finished_at": None,
}
TRANSCRIPT_ACCOUNT_LOCK = threading.RLock()
TRANSCRIPT_ACCOUNTS = []
TRANSCRIPT_ACCOUNT_INDEX = 0
DB_STATUS = {
    "available": False,
    "message": "database not initialized",
}

PROCESS_STAGES = [
    "准备阶段",
    "收房验房",
    "设计规划",
    "拆改阶段",
    "水电阶段",
    "防水阶段",
    "瓦工阶段",
    "木工阶段",
    "油工阶段",
    "主材安装",
    "定制柜安装",
    "厨卫安装",
    "灯具开关五金",
    "家电家具软装",
    "开荒保洁",
    "通风除醛",
    "入住验收",
    "待人工分类",
]
PROCESS_STAGE_ALIASES = {
    "验房": "收房验房",
    "收房": "收房验房",
    "设计": "设计规划",
    "规划": "设计规划",
    "拆改": "拆改阶段",
    "水电": "水电阶段",
    "防水": "防水阶段",
    "瓦工": "瓦工阶段",
    "泥瓦": "瓦工阶段",
    "木工": "木工阶段",
    "油工": "油工阶段",
    "主材": "主材安装",
    "定制": "定制柜安装",
    "橱柜": "定制柜安装",
    "厨卫": "厨卫安装",
    "灯具": "灯具开关五金",
    "开关五金": "灯具开关五金",
    "软装": "家电家具软装",
    "家具软装": "家电家具软装",
    "家电": "家电家具软装",
    "保洁": "开荒保洁",
    "除醛": "通风除醛",
    "通风": "通风除醛",
    "入住": "入住验收",
    "验收": "入住验收",
}

TAGS = {
    "space_tags": ["厨房", "卫生间", "客厅", "卧室", "阳台", "玄关", "全屋", "未提及"],
    "topic_tags": [
        "预算",
        "材料",
        "环保",
        "验收",
        "避坑",
        "合同",
        "增项",
        "品牌",
        "尺寸",
        "维修",
        "照明",
        "厨电",
        "全屋定制",
        "五金",
        "家电",
        "家具",
        "软装",
        "未提及",
    ],
    "stance": ["明确推荐", "明确不推荐", "有条件", "价格建议", "未明确"],
}


PG_DSN = os.environ.get("DATABASE_URL", "").strip()
ADMIN_SESSION_SECRET = os.environ.get("ADMIN_SESSION_SECRET", "").strip() or hashlib.sha256(
    f"{ADMIN_PASSWORD}:{PG_DSN}:{ROOT}".encode("utf-8")
).hexdigest()


def now():
    return int(time.time())


def time_label():
    return time.strftime("%H:%M:%S")


def new_id(prefix):
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


def queue_log(message):
    with QUEUE_JOB_LOCK:
        QUEUE_JOB["logs"].append(f"[{time_label()}] {message}")
        QUEUE_JOB["logs"] = QUEUE_JOB["logs"][-300:]


def queue_snapshot():
    with QUEUE_JOB_LOCK:
        return {
            "job_id": QUEUE_JOB["job_id"],
            "running": QUEUE_JOB["running"],
            "logs": list(QUEUE_JOB["logs"]),
            "processed": list(QUEUE_JOB["processed"]),
            "failed": list(QUEUE_JOB["failed"]),
            "remaining": QUEUE_JOB["remaining"],
            "started_at": QUEUE_JOB["started_at"],
            "finished_at": QUEUE_JOB["finished_at"],
            "cancel_requested": QUEUE_JOB.get("cancel_requested", False),
        }


def reserve_queue_job(prefix="job"):
    job_id = f"{prefix}_{time.strftime('%Y%m%d_%H%M%S')}"
    with QUEUE_JOB_LOCK:
        if QUEUE_JOB["running"]:
            return None
        QUEUE_JOB.update(
            {
                "job_id": job_id,
                "running": True,
                "logs": [],
                "processed": [],
                "failed": [],
                "remaining": None,
                "started_at": now(),
                "finished_at": None,
                "cancel_requested": False,
            }
        )
    return job_id


def queue_cancel_requested():
    with QUEUE_JOB_LOCK:
        return bool(QUEUE_JOB.get("cancel_requested"))


def request_queue_cancel():
    with QUEUE_JOB_LOCK:
        if not QUEUE_JOB["running"]:
            return False
        QUEUE_JOB["cancel_requested"] = True
    queue_log("已请求暂停，当前步骤结束后停止队列")
    return True


def douyin_login_snapshot():
    with DOUYIN_LOGIN_LOCK:
        return dict(DOUYIN_LOGIN_JOB)


def json_dumps(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def parse_cookie_header(value):
    cookies = {}
    for part in str(value or "").split(";"):
        if "=" not in part:
            continue
        key, raw_value = part.split("=", 1)
        key = key.strip()
        if key:
            cookies[key] = raw_value.strip()
    return cookies


def sign_admin_session(payload):
    return hmac.new(ADMIN_SESSION_SECRET.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()


def make_admin_session_value():
    issued_at = str(now())
    nonce = secrets.token_urlsafe(18)
    payload = f"{issued_at}.{nonce}"
    return f"{payload}.{sign_admin_session(payload)}"


def validate_admin_session_value(value):
    parts = str(value or "").split(".")
    if len(parts) != 3:
        return False
    issued_at, nonce, signature = parts
    payload = f"{issued_at}.{nonce}"
    expected = sign_admin_session(payload)
    if not hmac.compare_digest(signature, expected):
        return False
    try:
        issued_at_int = int(issued_at)
    except ValueError:
        return False
    return 0 < issued_at_int <= now() and now() - issued_at_int <= ADMIN_SESSION_MAX_AGE_SECONDS


def is_admin_request(handler):
    cookies = parse_cookie_header(handler.headers.get("Cookie", ""))
    return validate_admin_session_value(cookies.get(ADMIN_SESSION_COOKIE))


def admin_session_payload(handler):
    authenticated = is_admin_request(handler)
    return {
        "authenticated": authenticated,
        "configured": bool(ADMIN_PASSWORD),
        "max_age": ADMIN_SESSION_MAX_AGE_SECONDS,
    }


def require_admin(handler):
    if not ADMIN_PASSWORD:
        handler.send_error_json(503, "admin password is not configured")
        return False
    if not is_admin_request(handler):
        handler.send_error_json(401, "admin login required")
        return False
    return True


def json_loads(value, fallback):
    if value in (None, ""):
        return fallback
    if isinstance(value, (list, dict)):
        return value
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return fallback


def jsonb_value(value, fallback=None):
    if value in (None, ""):
        value = fallback
    return Json(value)


def raw_response_jsonb(raw_response):
    if not raw_response:
        return None
    try:
        return Json(json.loads(raw_response))
    except (TypeError, json.JSONDecodeError):
        return Json({"raw": raw_response})


def parse_published_at(value):
    text = str(value or "").strip()
    if not text:
        return None
    formats = (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
    )
    for fmt in formats:
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


from psycopg2.pool import ThreadedConnectionPool

_pool = None
_pool_lock = threading.Lock()


def _get_pool():
    global _pool
    if _pool is not None:
        return _pool
    with _pool_lock:
        if _pool is not None:
            return _pool
        if not PG_DSN:
            raise RuntimeError("DATABASE_URL is not configured")
        _pool = ThreadedConnectionPool(1, 8, PG_DSN, cursor_factory=RealDictCursor)
        return _pool


class PGConnection:
    def __init__(self, conn):
        self._conn = conn
        self._conn.autocommit = True

    def execute(self, sql, params=None):
        cur = self._conn.cursor()
        cur.execute(sql, params)
        return cur

    def commit(self):
        self._conn.commit()

    def close(self):
        _get_pool().putconn(self._conn)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def connect():
    pool = _get_pool()
    conn = pool.getconn()
    return PGConnection(conn)


def check_database():
    try:
        with connect() as conn:
            conn.execute("SELECT 1")
        DB_STATUS["available"] = True
        DB_STATUS["message"] = "ok"
        return True
    except Exception as exc:
        DB_STATUS["available"] = False
        DB_STATUS["message"] = str(exc)
        return False


def read_json(handler):
    length = int(handler.headers.get("Content-Length", "0"))
    if length <= 0:
        return {}
    raw = handler.rfile.read(length).decode("utf-8")
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid json: {exc}") from exc


def require_fields(payload, fields):
    missing = [field for field in fields if not str(payload.get(field, "")).strip()]
    if missing:
        raise ValueError(f"missing fields: {', '.join(missing)}")


@contextmanager
def video_process_lock(video_id):
    with VIDEO_PROCESS_LOCKS_LOCK:
        lock = VIDEO_PROCESS_LOCKS.get(video_id)
        if lock is None:
            lock = threading.RLock()
            VIDEO_PROCESS_LOCKS[video_id] = lock
    with lock:
        yield


def query_int(query, key, default, minimum=0, maximum=None):
    raw = (query.get(key) or [""])[0]
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = default
    value = max(minimum, value)
    if maximum is not None:
        value = min(maximum, value)
    return value


def transcript_meta(transcript_text):
    length = len((transcript_text or "").strip())
    return length > 0, length


def video_has_saved_transcript(video):
    if not video:
        return False
    return bool(video.get("has_transcript")) or int(video.get("transcript_length") or 0) > 0 or bool(video.get("transcript_text"))


def video_status_for_processing_error(video):
    return "transcript_saved" if video_has_saved_transcript(video) else "transcript_failed"


def row_to_video(row):
    transcript_text = row["transcript_text"] or ""
    has_transcript, transcript_length = transcript_meta(transcript_text)
    return {
        "id": row["id"],
        "source_id": row["source_id"],
        "platform": row["platform"],
        "creator": row["creator"],
        "title": row["title"],
        "source_url": row["source_url"],
        "share_url": row["share_url"],
        "share_text": row["share_text"],
        "published_at": row["published_at"],
        "transcript_text": row["transcript_text"],
        "has_transcript": bool(row.get("has_transcript", has_transcript)),
        "transcript_length": int(row.get("transcript_length", transcript_length) or 0),
        "transcript_source": row["transcript_source"],
        "transcript_created_at": row["transcript_created_at"],
        "retry_count": row["retry_count"],
        "last_retry_at": row["last_retry_at"],
        "last_error": row["last_error"],
        "status": row["status"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def row_to_video_summary(row):
    return {
        "id": row["id"],
        "source_id": row["source_id"],
        "platform": row["platform"],
        "creator": row["creator"],
        "title": row["title"],
        "source_url": row["source_url"],
        "share_url": row["share_url"],
        "share_text": row["share_text"],
        "published_at": row["published_at"],
        "has_transcript": bool(row["has_transcript"]),
        "transcript_length": int(row["transcript_length"] or 0),
        "transcript_source": row["transcript_source"],
        "transcript_created_at": row["transcript_created_at"],
        "retry_count": row["retry_count"],
        "last_retry_at": row["last_retry_at"],
        "last_error": row["last_error"],
        "status": row["status"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "claim_count": int(row["claim_count"] or 0),
    }


def row_to_claim(row):
    return {
        "id": row["id"],
        "video_id": row["video_id"],
        "extraction_run_id": row["extraction_run_id"],
        "object_name": row["object_name"],
        "stance": row["stance"],
        "process_stage": row["process_stage"],
        "space_tags": json_loads(row["space_tags"], []),
        "topic_tags": json_loads(row["topic_tags"], []),
        "original_conclusion": row["original_conclusion"],
        "original_reasons": json_loads(row["original_reasons"], []),
        "conditions": row["conditions"],
        "alternatives": json_loads(row["alternatives"], []),
        "price_info": row["price_info"],
        "source_video_url": row["source_video_url"],
        "created_at": row["created_at"],
    }


def row_to_source(row):
    return {
        "id": row["id"],
        "platform": row["platform"],
        "name": row["name"],
        "profile_url": row["profile_url"],
        "priority": row["priority"],
        "status": row["status"],
        "notes": row["notes"],
        "created_at": row["created_at"],
        "video_count": row["video_count"],
        "claim_count": row["claim_count"],
        "pending_count": row["pending_count"],
    }


def build_extract_prompt(video):
    taxonomy = {
        "process_stages": PROCESS_STAGES,
        "tags": TAGS,
        "output_schema": {
            "video_summary": {
                "title": "string",
                "source_url": "string",
                "platform": "string",
                "creator": "string",
                "main_topics": ["string"],
            },
            "filter_reason": "none|speech_unclear|promotion_only|no_general_knowledge|brand_model_only|case_showcase_only|duplicate_or_too_thin",
            "filter_message": "string",
            "claims": [
                {
                    "object_name": "string",
                    "stance": "明确推荐|明确不推荐|有条件|价格建议|未明确",
                    "process_stage": "one of process_stages",
                    "space_tags": ["one or more from space_tags"],
                    "topic_tags": ["one or more from topic_tags"],
                    "original_conclusion": "string or 未提及",
                    "original_reasons": ["string"],
                    "conditions": "string or 未提及",
                    "alternatives": ["string"],
                    "price_info": "string or 未提及",
                    "source_video_url": "string",
                }
            ],
        },
    }
    few_shot_example = {
        "input": "铺瓷砖之前一定要先泡砖，吸水率高的砖要泡够两小时，不然上墙以后容易空鼓脱落。铺完之后留缝不能小于2毫米，用十字卡控制间距。",
        "output": {
            "video_summary": {
                "title": "示例",
                "source_url": "",
                "platform": "",
                "creator": "",
                "main_topics": ["瓷砖铺贴", "空鼓预防"]
            },
            "filter_reason": "none",
            "filter_message": "",
            "claims": [
                {
                    "object_name": "瓷砖铺贴前泡砖",
                    "stance": "明确推荐",
                    "process_stage": "瓦工阶段",
                    "space_tags": ["未提及"],
                    "topic_tags": ["材料"],
                    "original_conclusion": "吸水率高的砖铺前需泡水两小时，否则易空鼓脱落",
                    "original_reasons": ["砖体吸水率高，不泡水会从水泥中大量吸水导致粘结失效"],
                    "conditions": "适用于吸水率高的瓷砖",
                    "alternatives": [],
                    "price_info": "未提及",
                    "source_video_url": ""
                },
                {
                    "object_name": "瓷砖留缝",
                    "stance": "价格建议",
                    "process_stage": "瓦工阶段",
                    "space_tags": ["未提及"],
                    "topic_tags": ["材料"],
                    "original_conclusion": "留缝不能小于2毫米，用十字卡控制间距",
                    "original_reasons": [],
                    "conditions": "未提及",
                    "alternatives": [],
                    "price_info": "未提及",
                    "source_video_url": ""
                }
            ]
        }
    }
    promotion_only_example = {
        "input": "今天这款华凌518进群抢，三千出头包邮，优惠券限时，想要价格的打在评论区，兄弟们等我好消息。",
        "output": {
            "video_summary": {
                "title": "示例",
                "source_url": "",
                "platform": "",
                "creator": "",
                "main_topics": ["促销推广"]
            },
            "filter_reason": "promotion_only",
            "filter_message": "纯推广促销或带货引流，没有可复用的装修知识或产品选购重点",
            "claims": []
        }
    }
    speech_unclear_example = {
        "input": "这个就那个啊，咱们家人们哈，它这个不串那个，零千平建一机进位送，反正就这么整，懂的都懂。",
        "output": {
            "video_summary": {
                "title": "示例",
                "source_url": "",
                "platform": "",
                "creator": "",
                "main_topics": ["语义不清"]
            },
            "filter_reason": "speech_unclear",
            "filter_message": "口语化或语音识别错误严重，无法可靠判断具体装修观点",
            "claims": []
        }
    }

    return f"""你是装修视频文案结构化提取器。

核心规则：
1. 只能依据输入文案原文提取信息，禁止补充、推断、扩写、改写为新建议。
2. 原文没有明确说到的信息，字段填写"未提及"或空数组。
3. 原文有多个装修对象时，拆成多条 claims。
4. 原文有价格、条件、替代做法时，分别放入对应字段。
5. process_stage 和 tags 只能从给定分类中选择；如果无法可靠归类，process_stage 填"待人工分类"，标签填"未提及"。
6. 没有通用装修知识、也没有该类产品通用选购重点时，不生成 claims。
7. 商业推广中的品牌名、系列名、具体型号不作为观点对象；如果原文讲的是产品，只提炼通用选购重点或关键指标，例如吸力、能耗、噪音、容量、滤芯成本、是否易清洁、是否环保、是否耐用。
8. 如果一条内容只有品牌/型号宣传，没有通用装修知识或产品选购重点，直接跳过，不生成观点。
9. 不要输出解释，不要输出 Markdown，只输出 JSON 对象。第一个字符必须是 {{，最后一个字符必须是 }}。
10. 文案来自语音识别，可能存在同音字或谐音错误（例如"空鼓"误识别为"空古"，"腻子"误识别为"泥子"）。请根据上下文语义理解原意进行提取；若某段文字因识别错误导致语义不可判断，对应字段填"未提及"，不生成错误观点。
11. 先判断文案是否值得提取：如果整体是纯推广、促销、带货、进群、抢购、优惠券、粉丝福利、价格引流、联系方式引流，且没有通用装修知识或产品选购重点，claims 必须为空，filter_reason 填 promotion_only。
12. 如果文案口语化严重、断句混乱、语音识别错乱、关键对象和结论无法可靠还原，claims 必须为空，filter_reason 填 speech_unclear，不要猜测或补写观点。
13. 如果语义清楚但只是在展示生活、案例、品牌型号、价格活动，没有通用装修知识或产品选购重点，claims 必须为空，filter_reason 填 no_general_knowledge。
14. 如果只有品牌、型号、系列、单品名称、价格口播，没有通用参数/指标/做法，claims 必须为空，filter_reason 填 brand_model_only。
15. 如果只是展示装修案例、效果、风格、生活方式，没有明确可复用做法或选购指标，claims 必须为空，filter_reason 填 case_showcase_only。
16. 如果内容过短、重复、碎片化，无法形成完整对象+结论，claims 必须为空，filter_reason 填 duplicate_or_too_thin。
17. 有可提取观点时，filter_reason 填 none，filter_message 填空字符串；无观点时，claims 必须为空，filter_message 用一句中文说明过滤原因。

系统分类：
{json_dumps(taxonomy)}

正向提取示例（仅演示格式和粒度，不作为内容参考）：
输入文案：{few_shot_example["input"]}
期望输出：{json_dumps(few_shot_example["output"])}

纯推广过滤示例：
输入文案：{promotion_only_example["input"]}
期望输出：{json_dumps(promotion_only_example["output"])}

口语/识别错误过滤示例：
输入文案：{speech_unclear_example["input"]}
期望输出：{json_dumps(speech_unclear_example["output"])}

视频元数据：
{json_dumps({
  "title": video["title"],
  "creator": video["creator"],
  "platform": video["platform"],
  "source_url": video["source_url"],
})}

视频文案：
{video["transcript_text"] or ""}
"""


BRAND_MODEL_PATTERN = re.compile(r"[A-Za-z]{2,}\d+[A-Za-z0-9-]*|[A-Z]{2,}[A-Za-z0-9-]*\d+")
GENERIC_PRODUCT_HINTS = (
    "冰箱",
    "洗衣机",
    "洗碗机",
    "净水器",
    "油烟机",
    "烟机",
    "燃气灶",
    "马桶",
    "花洒",
    "电视",
    "空调",
    "扫地机器人",
    "床垫",
    "窗帘",
    "瓷砖",
    "乳胶漆",
    "柜子",
    "板材",
    "地板",
    "浴缸",
    "台盆",
)
GENERIC_KNOWLEDGE_HINTS = (
    # 产品选购类
    "指标",
    "参数",
    "吸力",
    "能耗",
    "噪音",
    "容量",
    "环保",
    "耐用",
    "寿命",
    "滤芯",
    "维修",
    "清洁",
    "避坑",
    "实用",
    "推荐",
    "不推荐",
    "建议",
    "选",
    "别买",
    "不要",
    "安装",
    "防水",
    "收纳",
    "预算",
    # 施工工艺类
    "铺贴",
    "铺设",
    "找平",
    "空鼓",
    "腻子",
    "开槽",
    "收口",
    "美缝",
    "留缝",
    "坡度",
    "上反",
    "基层",
    "打底",
    "养护",
    "泡水",
    "闭水",
    "涂刷",
    "批刮",
    "阴角",
    "阳角",
    "开裂",
    "渗漏",
    "验收",
    "测试",
    "下水",
    "排水",
    "地漏",
    "回填",
    "包管",
    "拆墙",
    "砌墙",
    "开洞",
    "打孔",
    "固定",
    "密封",
    "防霉",
    "防潮",
    "隔音",
    "保温",
    "承重",
    "配比",
    "厚度",
    "间距",
    "水平",
    "垂直",
    "误差",
)


def normalize_text_value(value):
    return str(value or "").strip()


def normalize_list_value(value):
    if not isinstance(value, list):
        return []
    return [str(item or "").strip() for item in value if str(item or "").strip()]


def normalize_process_stage(value):
    stage = normalize_text_value(value)
    if stage in PROCESS_STAGES:
        return stage
    if stage in PROCESS_STAGE_ALIASES:
        return PROCESS_STAGE_ALIASES[stage]
    compact_stage = re.sub(r"[\s/／、,，]+", "", stage)
    if compact_stage in PROCESS_STAGE_ALIASES:
        return PROCESS_STAGE_ALIASES[compact_stage]
    for alias, normalized in PROCESS_STAGE_ALIASES.items():
        if alias and alias in compact_stage:
            return normalized
    return "待人工分类"


def claim_is_all_unmentioned(claim):
    reasons = normalize_list_value(claim.get("original_reasons"))
    alternatives = normalize_list_value(claim.get("alternatives"))
    stage = normalize_text_value(claim.get("process_stage")) or "待人工分类"
    spaces = normalize_list_value(claim.get("space_tags")) or ["未提及"]
    topics = normalize_list_value(claim.get("topic_tags")) or ["未提及"]
    stance = normalize_text_value(claim.get("stance")) or "未明确"
    conclusion = normalize_text_value(claim.get("original_conclusion")) or "未提及"
    conditions = normalize_text_value(claim.get("conditions")) or "未提及"
    price_info = normalize_text_value(claim.get("price_info")) or "未提及"
    reasons_empty = not reasons or all(item == "未提及" for item in reasons)
    alternatives_empty = not alternatives or all(item == "未提及" for item in alternatives)
    return (
        stage == "待人工分类"
        and all(item == "未提及" for item in spaces)
        and all(item == "未提及" for item in topics)
        and stance == "未明确"
        and conclusion == "未提及"
        and conditions == "未提及"
        and price_info == "未提及"
        and reasons_empty
        and alternatives_empty
    )


def claim_has_generic_knowledge(claim):
    fields = [
        normalize_text_value(claim.get("object_name")),
        normalize_text_value(claim.get("original_conclusion")),
        normalize_text_value(claim.get("conditions")),
        normalize_text_value(claim.get("price_info")),
        " ".join(normalize_list_value(claim.get("original_reasons"))),
        " ".join(normalize_list_value(claim.get("alternatives"))),
        " ".join(normalize_list_value(claim.get("topic_tags"))),
    ]
    text = " ".join(part for part in fields if part)
    return any(hint in text for hint in GENERIC_KNOWLEDGE_HINTS)


def claim_is_brand_model_only(claim):
    object_name = normalize_text_value(claim.get("object_name"))
    conclusion = normalize_text_value(claim.get("original_conclusion"))
    reasons = " ".join(normalize_list_value(claim.get("original_reasons")))
    combined = " ".join([object_name, conclusion, reasons]).strip()
    if not combined:
        return True
    has_product_class = any(hint in combined for hint in GENERIC_PRODUCT_HINTS)
    has_model_pattern = bool(BRAND_MODEL_PATTERN.search(combined))
    return has_model_pattern and not claim_has_generic_knowledge(claim) and not has_product_class


FILTER_REASON_MESSAGES = {
    "promotion_only": "无有效内容：纯推广促销或带货引流，无通用装修知识或产品选购重点",
    "speech_unclear": "无有效内容：口语化或识别错误严重，无法可靠提取观点",
    "no_general_knowledge": "无有效内容：无通用装修知识或产品选购重点",
    "brand_model_only": "无有效内容：只有品牌型号或单品价格，没有通用选购指标",
    "case_showcase_only": "无有效内容：仅展示案例效果，没有可复用装修做法",
    "duplicate_or_too_thin": "无有效内容：内容过短、重复或碎片化，无法形成可靠观点",
}


def normalize_filter_reason(value):
    reason = normalize_text_value(value)
    if reason in FILTER_REASON_MESSAGES:
        return reason
    return "no_general_knowledge"


def dropped_claim_filter_reason(dropped_claims):
    reasons = [item.get("reason") for item in dropped_claims or [] if isinstance(item, dict)]
    if reasons and all(reason == "brand_model_only" for reason in reasons):
        return "brand_model_only"
    if reasons and all(reason in ("all_unmentioned", "invalid_claim_type") for reason in reasons):
        return "speech_unclear"
    return "no_general_knowledge"


def build_filtered_message(extracted, dropped_claims):
    reason = normalize_filter_reason((extracted or {}).get("filter_reason"))
    if reason == "no_general_knowledge" and dropped_claims:
        reason = dropped_claim_filter_reason(dropped_claims)
    message = normalize_text_value((extracted or {}).get("filter_message"))
    if message and reason != "none":
        return message if message.startswith("无有效内容") else f"无有效内容：{message}"
    return FILTER_REASON_MESSAGES.get(reason, FILTER_REASON_MESSAGES["no_general_knowledge"])


def sanitize_claims(claims):
    filtered = []
    dropped = []
    for claim in claims or []:
        if not isinstance(claim, dict):
            dropped.append({"reason": "invalid_claim_type"})
            continue
        if claim_is_all_unmentioned(claim):
            dropped.append({"reason": "all_unmentioned", "object_name": claim.get("object_name")})
            continue
        if claim_is_brand_model_only(claim):
            dropped.append({"reason": "brand_model_only", "object_name": claim.get("object_name")})
            continue
        if not claim_has_generic_knowledge(claim):
            dropped.append({"reason": "no_generic_knowledge", "object_name": claim.get("object_name")})
            continue
        claim["process_stage"] = normalize_process_stage(claim.get("process_stage"))
        filtered.append(claim)
    return filtered, dropped


def normalize_deepseek_response(response_body):
    text = (response_body or "").strip()
    if not text.startswith("data:"):
        return response_body

    content_parts = []
    reasoning_parts = []
    last_payload = None
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("data:"):
            continue
        chunk = line[5:].strip()
        if not chunk or chunk == "[DONE]":
            continue
        try:
            payload = json.loads(chunk)
        except json.JSONDecodeError:
            continue
        last_payload = payload
        for choice in payload.get("choices", []):
            delta = choice.get("delta") or {}
            content = delta.get("content")
            reasoning = delta.get("reasoning")
            if content:
                content_parts.append(content)
            if reasoning:
                reasoning_parts.append(reasoning)

    if not content_parts:
        content_parts = reasoning_parts
    model = (last_payload or {}).get("model", DEEPSEEK_MODEL)
    return json_dumps(
        {
            "id": (last_payload or {}).get("id", ""),
            "object": "chat.completion",
            "model": model,
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "".join(content_parts)}}],
        }
    )


def extract_json_object_from_text(text):
    text = (text or "").strip()
    start = text.find("{")
    if start < 0:
        return ""
    depth = 0
    in_string = False
    escape = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return ""


def parse_deepseek_content(response_body):
    response_body = normalize_deepseek_response(response_body)
    text = (response_body or "").strip()
    if not text:
        raise ValueError("deepseek_empty_response")

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        preview = text[:160].replace("\n", "\\n")
        raise ValueError(f"deepseek_invalid_json_prefix: {preview}") from exc

    choices = data.get("choices") or []
    if not choices:
        raise ValueError(f"deepseek_missing_choices: {json_dumps(data)[:200]}")

    message = choices[0].get("message") or {}
    content = (message.get("content") or "").strip()
    if not content:
        raise ValueError(f"deepseek_empty_content: {json_dumps(choices[0])[:200]}")

    try:
        return json.loads(content)
    except json.JSONDecodeError as exc:
        extracted_json = extract_json_object_from_text(content)
        if extracted_json:
            try:
                return json.loads(extracted_json)
            except json.JSONDecodeError:
                pass
        preview = content[:160].replace("\n", "\\n")
        raise ValueError(f"deepseek_content_not_json: 模型没有返回可解析的 JSON，开头内容：{preview}") from exc


def call_deepseek(prompt):
    api_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if not api_key:
        return None, "missing_api_key"

    payload = {
        "model": DEEPSEEK_MODEL,
        "messages": [
            {"role": "system", "content": "You extract structured JSON exactly as requested. Return only one JSON object. The first character must be { and the last character must be }. Do not explain."},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "stream": False,
    }
    if DEEPSEEK_GROUP:
        payload["group"] = DEEPSEEK_GROUP
    base_url = DEEPSEEK_BASE_URL.rstrip("/")
    url = f"{base_url}/chat/completions"

    curl_body, curl_error = call_deepseek_with_curl(url, payload, api_key)
    if curl_body:
        return normalize_deepseek_response(curl_body), None
    if "deepseek_http_404" in (curl_error or "") and not base_url.endswith("/v1"):
        retry_body, retry_error = call_deepseek_with_curl(f"{base_url}/v1/chat/completions", payload, api_key)
        if retry_body:
            return normalize_deepseek_response(retry_body), None
        curl_error = f"{curl_error}; curl_retry: {retry_error}"

    body = json_dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return normalize_deepseek_response(response.read().decode("utf-8")), None
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        if exc.code == 404 and not base_url.endswith("/v1"):
            retry_url = f"{base_url}/v1/chat/completions"
            retry_request = urllib.request.Request(
                retry_url,
                data=body,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                method="POST",
            )
            try:
                with urllib.request.urlopen(retry_request, timeout=120) as retry_response:
                    return normalize_deepseek_response(retry_response.read().decode("utf-8")), None
            except Exception as retry_exc:
                python_error = f"deepseek_http_404_retry_failed: {retry_exc}"
                return None, truncate_error(f"{python_error}; curl_fallback: {curl_error}")
        python_error = f"deepseek_http_{exc.code}: {detail}"
    except Exception as exc:
        python_error = f"deepseek_error: {exc}"

    return None, truncate_error(f"{python_error}; curl_fallback: {curl_error}")


def call_deepseek_with_curl(url, payload, api_key):
    payload_file = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False) as file:
            payload_file = file.name
            file.write(json_dumps(payload))
        command = [
            "curl",
            "-sS",
            "-m",
            "120",
            "-w",
            "\n%{http_code}",
            url,
            "-H",
            f"Authorization: Bearer {api_key}",
            "-H",
            "Content-Type: application/json",
            "-d",
            f"@{payload_file}",
        ]
        result = subprocess.run(command, capture_output=True, text=True, timeout=130, check=False)
    except Exception as exc:
        return None, str(exc)
    finally:
        if payload_file:
            try:
                Path(payload_file).unlink(missing_ok=True)
            except Exception:
                pass
    if result.returncode != 0:
        return None, result.stderr.strip() or f"curl_exit_{result.returncode}"

    text, _, status_text = result.stdout.rpartition("\n")
    try:
        status_code = int(status_text)
    except ValueError:
        return None, f"invalid_curl_status: {result.stdout[:200]}"
    if 200 <= status_code < 300:
        return text, None
    return None, f"deepseek_http_{status_code}: {text}"


def truncate_error(message, limit=MAX_ERROR_MESSAGE_LENGTH):
    if len(message) <= limit:
        return message
    return f"{message[:limit]}...[truncated]"


def extract_first_url(text):
    match = re.search(r"https?://[^\s，。！？、)）]+", text or "")
    if not match:
        return ""
    return match.group(0).rstrip(".,;，。；")


def infer_platform(url):
    host = urlparse(url).netloc.lower()
    if "douyin" in host:
        return "抖音"
    if "xiaohongshu" in host or "xhslink" in host:
        return "小红书"
    if "bilibili" in host:
        return "B站"
    return "待识别"


def infer_title(share_text, transcript_text):
    text = (share_text or "").strip()
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"复制此链接.*$", "", text).strip()
    text = re.sub(r"^[\d.]+\s+\S+:\s*", "", text)
    if not text:
        text = (transcript_text or "").strip()
    compact = re.sub(r"\s+", " ", text)
    return compact[:36] or "待识别视频"


def canonical_video_url(url):
    url = (url or "").strip()
    douyin_match = re.search(r"douyin\.com/video/(\d+)", url)
    if douyin_match:
        return f"https://www.douyin.com/video/{douyin_match.group(1)}"
    return url


def truncate_text(value, limit=MAX_ERROR_MESSAGE_LENGTH):
    text = str(value or "")
    if len(text) <= limit:
        return text
    return f"{text[:limit]}...<truncated {len(text) - limit} chars>"


def stable_source_id(platform, profile_url):
    digest = hashlib.sha1(f"{platform}|{profile_url}".encode("utf-8")).hexdigest()[:12]
    return f"src_{digest}"


def save_collected_videos(conn, payload, items):
    platform = payload["platform"]
    creator = payload["creator"]
    profile_url = payload["profile_url"]
    source_id = payload.get("source_id") or stable_source_id(platform, profile_url)
    ts = now()
    conn.execute(
        """
        INSERT INTO sources (id, platform, name, profile_url, priority, status, notes, created_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT(id) DO UPDATE SET
          platform=excluded.platform,
          name=excluded.name,
          profile_url=excluded.profile_url,
          priority=excluded.priority,
          status=excluded.status,
          notes=excluded.notes
        """,
        (
            source_id,
            platform,
            creator,
            profile_url,
            payload.get("priority", "P0"),
            "active",
            payload.get("notes", ""),
            ts,
        ),
    )

    limit = int(payload.get("limit") or len(items))
    candidates = []
    for index, item in enumerate(items[:limit]):
        if not isinstance(item, dict):
            continue
        source_url = canonical_video_url(item.get("source_url") or item.get("url") or "")
        if not source_url:
            continue
        candidates.append((index, item, source_url))
    existing_urls = set()
    if candidates:
        existing_rows = conn.execute(
            "SELECT source_url FROM videos WHERE source_url = ANY(%s)",
            ([source_url for _, _, source_url in candidates],),
        ).fetchall()
        existing_urls = {row["source_url"] for row in existing_rows}

    saved = []
    created_count = 0
    duplicate_count = 0
    for index, item, source_url in candidates:
        title = (item.get("title") or "").strip() or f"{creator} 作品 {index + 1}"
        video_id = item.get("id") or new_id("vid")
        published_at = (item.get("published_at") or "").strip() or None
        published_at_ts = parse_published_at(published_at)
        conn.execute(
            """
            INSERT INTO videos (
              id, source_id, platform, creator, title, source_url, share_url, share_text, published_at, published_at_ts,
              transcript_text, transcript_source, transcript_created_at,
              has_transcript, transcript_length, status, created_at, updated_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT(source_url) DO UPDATE SET
              source_id=excluded.source_id,
              title=excluded.title,
              platform=excluded.platform,
              creator=excluded.creator,
              published_at=COALESCE(excluded.published_at, videos.published_at),
              published_at_ts=COALESCE(excluded.published_at_ts, videos.published_at_ts),
              status=CASE
                WHEN COALESCE(videos.has_transcript, false) THEN videos.status
                ELSE videos.status
              END,
              deleted_at=NULL,
              deleted_by=NULL,
              delete_reason=NULL,
              updated_at=excluded.updated_at
            """,
            (
                video_id,
                source_id,
                platform,
                creator,
                title,
                source_url,
                item.get("share_url") or source_url,
                item.get("share_text"),
                published_at,
                published_at_ts,
                None,
                None,
                None,
                False,
                0,
                "transcript_pending",
                ts,
                ts,
            ),
        )
        row = conn.execute("SELECT * FROM videos WHERE source_url = %s AND deleted_at IS NULL", (source_url,)).fetchone()
        video = row_to_video(row)
        is_duplicate = source_url in existing_urls
        video["dedupe_status"] = "duplicate" if is_duplicate else "created"
        saved.append(video)
        if is_duplicate:
            duplicate_count += 1
        else:
            created_count += 1

    return {
        "source_id": source_id,
        "videos": saved,
        "stats": {
            "received": len(items[:limit]),
            "saved": len(saved),
            "created": created_count,
            "duplicate": duplicate_count,
        },
    }


def run_douyin_collector(args, timeout=90):
    script = ROOT / "collector_douyin.py"
    collector_python = ROOT / ".venv" / "bin" / "python"
    command = [
        str(collector_python if collector_python.exists() else sys.executable),
        str(script),
        *args,
    ]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"douyin_collector_timeout: {exc}") from exc
    raw = (result.stdout or "").strip()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        detail = (result.stderr or raw or str(exc)).strip()
        raise RuntimeError(f"douyin_collector_invalid_output: {truncate_text(detail)}") from exc
    if result.returncode != 0 or not payload.get("ok"):
        message = payload.get("message") or payload.get("error") or "douyin_collector_failed"
        detail = {key: value for key, value in payload.items() if key not in ("ok", "message")}
        if detail:
            message = f"{message} | {json_dumps(detail)}"
        raise RuntimeError(message)
    return payload


def get_douyin_login_status():
    return run_douyin_collector(["--mode", "status"], timeout=20)


def run_douyin_login_job(profile_url, wait_seconds):
    with DOUYIN_LOGIN_LOCK:
        DOUYIN_LOGIN_JOB.update(
            {
                "running": True,
                "status": "running",
                "message": "已打开抖音登录窗口，请完成登录。",
                "logged_in": False,
                "cookie_count": 0,
                "valid_cookie_names": [],
                "started_at": now(),
                "finished_at": None,
            }
        )
    try:
        status = run_douyin_collector(
            [
                "--mode",
                "login",
                "--profile-url",
                profile_url or "https://www.douyin.com/",
                "--wait-seconds",
                str(wait_seconds),
            ],
            timeout=wait_seconds + 30,
        )
        with DOUYIN_LOGIN_LOCK:
            DOUYIN_LOGIN_JOB.update(
                {
                    "running": False,
                    "status": "logged_in",
                    "message": status.get("message") or "抖音登录态已保存。",
                    "logged_in": bool(status.get("logged_in")),
                    "cookie_count": int(status.get("cookie_count") or 0),
                    "valid_cookie_names": status.get("valid_cookie_names") or [],
                    "finished_at": now(),
                }
            )
    except Exception as exc:
        with DOUYIN_LOGIN_LOCK:
            DOUYIN_LOGIN_JOB.update(
                {
                    "running": False,
                    "status": "failed",
                    "message": truncate_error(str(exc)),
                    "logged_in": False,
                    "finished_at": now(),
                }
            )


def collect_douyin_profile(profile_url, limit, creator=""):
    payload = run_douyin_collector(
        [
            "--mode",
            "collect",
            "--profile-url",
            profile_url,
            "--creator",
            creator or "",
            "--limit",
            str(limit),
        ],
        timeout=90,
    )
    videos = payload.get("videos") or []
    if not isinstance(videos, list) or not videos:
        raise RuntimeError("douyin_collector_empty")
    return videos


def openssl_aes_crypt(data, mode):
    command = [
        "openssl",
        "enc",
        f"-aes-128-cbc",
        f"-{mode}",
        "-K",
        TRANSCRIPT_AES_KEY_HEX,
        "-iv",
        TRANSCRIPT_AES_IV_HEX,
        "-nopad",
    ]
    try:
        result = subprocess.run(command, input=data, capture_output=True, timeout=20, check=False)
    except Exception as exc:
        raise RuntimeError(f"openssl_{mode}_failed: {exc}") from exc
    if result.returncode != 0:
        raise RuntimeError(result.stderr.decode("utf-8", errors="replace") or f"openssl_{mode}_{result.returncode}")
    return result.stdout


def zero_pad(data):
    pad_size = (-len(data)) % 16
    return data + (b"\0" * pad_size)


def transcript_encrypt(value):
    text = value if isinstance(value, str) else json_dumps(value)
    encrypted = openssl_aes_crypt(zero_pad(text.encode("utf-8")), "e")
    return b64encode(encrypted).decode("ascii")


def transcript_decrypt(value):
    decrypted = openssl_aes_crypt(b64decode(value), "d").rstrip(b"\0")
    text = decrypted.decode("utf-8")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def normalize_transcript_account(account, index):
    if not isinstance(account, dict):
        return None
    email = str(account.get("email") or "").strip()
    token = str(account.get("token") or "").strip()
    password = str(account.get("password") or "")
    if not token and (not email or not password):
        return None
    return {
        "id": account.get("id") or f"account_{index}",
        "label": account.get("label") or email or f"账号 {index}",
        "email": email,
        "password": password,
        "token": token,
        "runtime_token": token,
        "cooldown_minutes": int(account.get("cooldown_minutes") or 10),
        "enabled": bool(account.get("enabled", True)),
        "status": account.get("status") or "available",
        "cooldown_until": 0,
        "last_error": "",
    }


def load_transcript_accounts():
    accounts = []
    if TRANSCRIPT_ACCOUNTS_PATH.exists():
        try:
            payload = json.loads(TRANSCRIPT_ACCOUNTS_PATH.read_text(encoding="utf-8"))
            for index, account in enumerate(payload.get("accounts") or [], start=1):
                normalized = normalize_transcript_account(account, index)
                if normalized:
                    accounts.append(normalized)
        except Exception as exc:
            print(f"Failed to load {TRANSCRIPT_ACCOUNTS_PATH}: {exc}", file=sys.stderr)
    if TRANSCRIPTGENERATE_TOKEN or (TRANSCRIPTGENERATE_EMAIL and TRANSCRIPTGENERATE_PASSWORD):
        accounts.insert(
            0,
            {
                "id": "config_default",
                "label": TRANSCRIPTGENERATE_EMAIL or "config_default",
                "email": TRANSCRIPTGENERATE_EMAIL,
                "password": TRANSCRIPTGENERATE_PASSWORD,
                "token": TRANSCRIPTGENERATE_TOKEN,
                "runtime_token": TRANSCRIPTGENERATE_TOKEN,
                "cooldown_minutes": 10,
                "enabled": True,
                "status": "available",
                "cooldown_until": 0,
                "last_error": "",
            },
        )
    return accounts


def get_transcript_accounts():
    global TRANSCRIPT_ACCOUNTS
    with TRANSCRIPT_ACCOUNT_LOCK:
        if not TRANSCRIPT_ACCOUNTS:
            TRANSCRIPT_ACCOUNTS = load_transcript_accounts()
        return TRANSCRIPT_ACCOUNTS


def transcript_account_label(account):
    label = account.get("label") or account.get("email") or account.get("id") or "未命名账号"
    email = account.get("email") or ""
    return f"{label}<{email}>" if email and email not in label else label


def transcript_response_text(response):
    if isinstance(response, dict):
        return " ".join(str(response.get(key) or "") for key in ("msg", "message", "error", "code"))
    return str(response or "")


def transcript_is_limit_response(response):
    if isinstance(response, dict) and response.get("code") in (601, "601"):
        return True
    text = transcript_response_text(response).lower()
    return any(
        keyword in text
        for keyword in (
            "上限",
            "额度",
            "权益次数",
            "次数不足",
            "次数已用完",
            "已用尽",
            "获取更多次数",
            "limit",
            "quota",
            "会员",
            "premium",
            "subscribe",
        )
    )


def transcript_is_auth_response(response):
    if isinstance(response, dict) and response.get("code") in (401, 403):
        return True
    text = transcript_response_text(response).lower()
    return any(keyword in text for keyword in ("token", "登录", "未授权", "unauthorized", "forbidden", "401", "403"))


def transcript_decode_error_detail(detail):
    text = str(detail or "").strip()
    if not text:
        return ""
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        parsed = text
    if isinstance(parsed, str):
        try:
            return transcript_decrypt(parsed)
        except Exception:
            return parsed
    return parsed


def transcript_login_account(account):
    if not account.get("email") or not account.get("password"):
        raise RuntimeError("missing_email_password")
    response = transcript_request_once(
        "/login",
        method="POST",
        payload={
            "username": account["email"],
            "password": account["password"],
            "appType": "transcript",
            "appClient": "web",
        },
        auth=False,
        retry_auth=False,
        account=account,
    )
    if not isinstance(response, dict) or response.get("code") != 200 or not response.get("token"):
        raise RuntimeError(f"login_failed: {response}")
    account["runtime_token"] = str(response["token"]).strip()
    account["status"] = "available"
    account["last_error"] = ""
    return account["runtime_token"]


def transcript_login():
    global TRANSCRIPTGENERATE_TOKEN
    if not TRANSCRIPTGENERATE_EMAIL or not TRANSCRIPTGENERATE_PASSWORD:
        raise RuntimeError("transcriptgenerate_login_missing_credentials")
    account = {
        "label": TRANSCRIPTGENERATE_EMAIL,
        "email": TRANSCRIPTGENERATE_EMAIL,
        "password": TRANSCRIPTGENERATE_PASSWORD,
        "runtime_token": "",
    }
    response = transcript_request_once(
        "/login",
        method="POST",
        payload={
            "username": TRANSCRIPTGENERATE_EMAIL,
            "password": TRANSCRIPTGENERATE_PASSWORD,
            "appType": "transcript",
            "appClient": "web",
        },
        auth=False,
        retry_auth=False,
        account=account,
    )
    if not isinstance(response, dict) or response.get("code") != 200 or not response.get("token"):
        raise RuntimeError(f"transcriptgenerate_login_failed: {response}")
    TRANSCRIPTGENERATE_TOKEN = str(response["token"]).strip()
    return TRANSCRIPTGENERATE_TOKEN


def transcript_auth_expired(response):
    if not isinstance(response, dict):
        return False
    code = response.get("code")
    message = str(response.get("msg") or response.get("message") or "").lower()
    return code in (401, 403) or "token" in message or "登录" in message or "unauthorized" in message


def transcript_request(path, method="GET", payload=None, params=None):
    accounts = [account for account in get_transcript_accounts() if account.get("enabled", True)]
    if not accounts:
        return transcript_request_once(path, method=method, payload=payload, params=params, auth=True, retry_auth=True)

    now_ts = time.time()
    errors = []
    with TRANSCRIPT_ACCOUNT_LOCK:
        start_index = TRANSCRIPT_ACCOUNT_INDEX % len(accounts)
    ordered_accounts = accounts[start_index:] + accounts[:start_index]
    for account in ordered_accounts:
        label = transcript_account_label(account)
        if account.get("cooldown_until", 0) > now_ts:
            errors.append(f"{label}: 冷却中")
            continue
        try:
            return transcript_request_with_account(account, path, method=method, payload=payload, params=params)
        except RuntimeError as exc:
            errors.append(f"{label}: {truncate_error(str(exc), 220)}")
            continue
    raise RuntimeError("所有文案账号不可用：" + "；".join(errors))


def transcript_request_with_account(account, path, method="GET", payload=None, params=None):
    label = transcript_account_label(account)
    if not account.get("runtime_token") and account.get("email") and account.get("password"):
        transcript_login_account(account)
    try:
        response = transcript_request_once(path, method=method, payload=payload, params=params, auth=True, retry_auth=False, account=account)
    except RuntimeError as exc:
        detail = str(exc)
        if "transcriptgenerate_http_401" in detail or "transcriptgenerate_http_403" in detail:
            if account.get("email") and account.get("password"):
                try:
                    transcript_login_account(account)
                    response = transcript_request_once(path, method=method, payload=payload, params=params, auth=True, retry_auth=False, account=account)
                except Exception as login_exc:
                    account["status"] = "auth_failed"
                    account["last_error"] = truncate_error(str(login_exc))
                    raise RuntimeError(f"{label} 登录失效且重登失败：{truncate_error(str(login_exc), 500)}") from login_exc
            else:
                account["status"] = "auth_failed"
                account["last_error"] = truncate_error(detail)
                raise RuntimeError(f"{label} token 失效且未配置密码") from exc
        else:
            account["status"] = "failed"
            account["last_error"] = truncate_error(detail)
            raise
    if transcript_auth_expired(response):
        if account.get("email") and account.get("password"):
            try:
                transcript_login_account(account)
                response = transcript_request_once(path, method=method, payload=payload, params=params, auth=True, retry_auth=False, account=account)
            except Exception as login_exc:
                account["status"] = "auth_failed"
                account["last_error"] = truncate_error(str(login_exc))
                raise RuntimeError(f"{label} token 失效且重登失败：{truncate_error(str(login_exc), 500)}") from login_exc
        else:
            account["status"] = "auth_failed"
            account["last_error"] = truncate_error(transcript_response_text(response))
            raise RuntimeError(f"{label} token 失效且未配置密码")
    if transcript_is_limit_response(response):
        account["status"] = "limited"
        account["cooldown_until"] = time.time() + int(account.get("cooldown_minutes") or 10) * 60
        account["last_error"] = truncate_error(transcript_response_text(response))
        raise RuntimeError(f"{label} 额度或账号上限：{truncate_error(transcript_response_text(response), 500)}")
    account["status"] = "available"
    account["last_error"] = ""
    with TRANSCRIPT_ACCOUNT_LOCK:
        global TRANSCRIPT_ACCOUNT_INDEX
        if account in TRANSCRIPT_ACCOUNTS:
            TRANSCRIPT_ACCOUNT_INDEX = TRANSCRIPT_ACCOUNTS.index(account)
    return response


def transcript_request_once(path, method="GET", payload=None, params=None, auth=True, retry_auth=True, account=None):
    if account is None and auth and not TRANSCRIPTGENERATE_TOKEN and TRANSCRIPTGENERATE_EMAIL and TRANSCRIPTGENERATE_PASSWORD:
        transcript_login()
    url = f"{TRANSCRIPT_API_BASE_URL}{path}"
    headers = {
        "Accept": "application/json",
        "Accept-Language": "zh-CN",
        "Origin": "https://www.transcriptgenerate.com",
        "Referer": "https://www.transcriptgenerate.com/zh-CN",
        "User-Agent": "Mozilla/5.0",
    }
    token = account.get("runtime_token") if account else TRANSCRIPTGENERATE_TOKEN
    if auth and token:
        headers["Authorization"] = f"Bearer {token}"
    data = None
    if method == "GET" and params:
        query = "&".join(f"{quote(str(key), safe='')}={quote(str(value), safe='')}" for key, value in params.items())
        url = f"{url}?{query}"
    elif method == "POST":
        data = json_dumps(transcript_encrypt(payload or {})).encode("utf-8")
        headers["Content-Type"] = "application/json"

    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        decoded_detail = transcript_decode_error_detail(detail)
        raise RuntimeError(f"transcriptgenerate_http_{exc.code}: {decoded_detail}") from exc
    except Exception as exc:
        raise RuntimeError(f"transcriptgenerate_error: {exc}") from exc

    try:
        parsed = json.loads(body)
    except json.JSONDecodeError:
        parsed = body
    if isinstance(parsed, str):
        parsed = transcript_decrypt(parsed)
    if account is None and auth and retry_auth and transcript_auth_expired(parsed):
        transcript_login()
        return transcript_request_once(path, method=method, payload=payload, params=params, auth=auth, retry_auth=False)
    return parsed


def extract_task_id(response):
    if isinstance(response, str):
        return response
    if not isinstance(response, dict):
        return ""
    for key in ("taskId", "task_id", "id", "data"):
        value = response.get(key)
        if isinstance(value, str):
            return value
        if isinstance(value, dict):
            nested = extract_task_id(value)
            if nested:
                return nested
    return ""


TRANSCRIPT_STRONG_KEYS = {
    "textContent",
    "transcript",
    "transcriptText",
    "transcript_text",
    "subtitle",
    "subtitles",
    "caption",
    "captions",
    "segments",
}
TRANSCRIPT_WEAK_KEYS = {"text", "content", "result", "description", "desc", "title"}
TRANSCRIPT_BLOCKED_KEYS = {
    "audioUrl",
    "cover",
    "createBy",
    "createTime",
    "errorMessage",
    "imageUrlList",
    "platform",
    "status",
    "taskId",
    "videoUrl",
    "videoUrlList",
    "workType",
    "workUrl",
}


def looks_like_url(value):
    return bool(re.match(r"^https?://", value or ""))


def collect_transcript_candidates(value, path="$"):
    candidates = []
    if isinstance(value, str):
        text = value.strip()
        if len(text) > 0:
            key = path.split(".")[-1].split("[")[0]
            if key in TRANSCRIPT_BLOCKED_KEYS or looks_like_url(text):
                return candidates
            candidates.append(
                {
                    "path": path,
                    "key": key,
                    "text": text,
                    "length": len(text),
                    "strong": key in TRANSCRIPT_STRONG_KEYS,
                    "weak": key in TRANSCRIPT_WEAK_KEYS,
                }
            )
        return candidates
    if isinstance(value, list):
        part_texts = []
        parent_key = path.split(".")[-1].split("[")[0]
        for index, item in enumerate(value):
            item_candidates = collect_transcript_candidates(item, f"{path}[{index}]")
            candidates.extend(item_candidates)
            strong_text = select_transcript_candidate(item_candidates, min_length=1, allow_weak=parent_key in TRANSCRIPT_STRONG_KEYS)
            if strong_text:
                part_texts.append(strong_text["text"])
        if len(part_texts) > 1:
            joined = "\n".join(part_texts).strip()
            candidates.append(
                {
                    "path": path,
                    "key": parent_key,
                    "text": joined,
                    "length": len(joined),
                    "strong": parent_key in TRANSCRIPT_STRONG_KEYS,
                    "weak": False,
                }
            )
        return candidates
    if isinstance(value, dict):
        for key, nested in value.items():
            candidates.extend(collect_transcript_candidates(nested, f"{path}.{key}"))
    return candidates


def select_transcript_candidate(candidates, min_length=MIN_TRANSCRIPT_LENGTH, allow_weak=True):
    usable = [
        item
        for item in candidates
        if item["length"] >= min_length and ((item["strong"] and not item["weak"]) if not allow_weak else True)
    ]
    if not usable:
        return None
    usable.sort(key=lambda item: (0 if item["strong"] else 1 if not item["weak"] else 2, -item["length"]))
    return usable[0]


def summarize_transcript_candidates(candidates, limit=8):
    summary = []
    for item in sorted(candidates, key=lambda candidate: candidate["length"], reverse=True)[:limit]:
        kind = "strong" if item["strong"] else "weak" if item["weak"] else "other"
        summary.append(f"{item['path']}={item['length']}({kind})")
    return ", ".join(summary) or "none"


def transcript_candidate_label(candidate):
    if not candidate:
        return "暂未发现可用文案"
    key = candidate.get("key") or ""
    length = int(candidate.get("length") or 0)
    if candidate.get("strong"):
        label = "完整文案"
    elif key in ("content", "title"):
        label = "标题或简介"
    elif candidate.get("weak"):
        label = "短文案"
    else:
        label = "候选文本"
    return f"{label}约 {length} 字"


def summarize_transcript_progress(candidates, selected=None):
    if selected:
        return f"已拿到完整文案，长度 {int(selected.get('length') or 0)} 字"
    best = select_transcript_candidate(candidates, min_length=1, allow_weak=True)
    if best:
        if best.get("strong"):
            return f"服务已返回一段文案，长度 {int(best.get('length') or 0)} 字，仍未达到入库长度要求"
        return f"服务已返回{transcript_candidate_label(best)}，还在等待完整文案"
    return "服务还在处理，暂未返回文案内容"


def extract_transcript_text(value):
    selected = select_transcript_candidate(collect_transcript_candidates(value), allow_weak=False)
    return selected["text"] if selected else ""


def fetch_transcript_from_transcriptgenerate(video_url, log=None):
    create_response = transcript_request(
        "/transcript/createTask",
        method="POST",
        payload={
            "appType": "transcript",
            "workUrl": video_url,
            "type": "text",
            "targetLanguage": "auto",
        },
    )
    task_id = extract_task_id(create_response)
    if not task_id:
        if transcript_is_limit_response(create_response):
            raise RuntimeError(f"transcriptgenerate_limit: {transcript_response_text(create_response)}")
        raise RuntimeError(f"transcript_task_id_missing: {create_response}")
    if log:
        log(f"文案服务已接收任务，任务号 {task_id}")

    last_response = None
    debug = {
        "task_id": task_id,
        "create_response": create_response,
        "polls": [],
        "candidate_summary": "",
        "selected_path": "",
        "selected_length": 0,
        "raw_excerpt": "",
    }
    for poll_index in range(TRANSCRIPT_MAX_POLLS):
        time.sleep(TRANSCRIPT_POLL_INTERVAL_SECONDS)
        last_response = transcript_request("/transcript/queryTask", method="GET", params={"taskId": task_id})
        candidates = collect_transcript_candidates(last_response)
        selected = select_transcript_candidate(candidates, allow_weak=False)
        poll_summary = {
            "index": poll_index + 1,
            "code": last_response.get("code") if isinstance(last_response, dict) else None,
            "msg": last_response.get("msg") if isinstance(last_response, dict) else "",
            "status": last_response.get("status") if isinstance(last_response, dict) else "",
            "candidate_summary": summarize_transcript_candidates(candidates),
            "selected_path": selected["path"] if selected else "",
            "selected_length": selected["length"] if selected else 0,
        }
        debug["polls"].append(poll_summary)
        debug["candidate_summary"] = poll_summary["candidate_summary"]
        debug["selected_path"] = poll_summary["selected_path"]
        debug["selected_length"] = poll_summary["selected_length"]
        debug["raw_excerpt"] = truncate_text(json_dumps(last_response), MAX_TRANSCRIPT_DEBUG_LENGTH)
        if log:
            log(f"第 {poll_index + 1} 次检查文案服务：{summarize_transcript_progress(candidates, selected)}")
        if selected:
            return {
                "task_id": task_id,
                "transcript_text": selected["text"],
                "raw_result": last_response,
                "debug": debug,
            }
        if isinstance(last_response, dict) and last_response.get("code") == 500:
            raise RuntimeError(last_response.get("msg") or "transcript_task_failed")

    short_candidate = select_transcript_candidate(collect_transcript_candidates(last_response), min_length=1, allow_weak=True) if last_response else None
    if short_candidate:
        debug["selected_path"] = short_candidate["path"]
        debug["selected_length"] = short_candidate["length"]
        raise RuntimeError(
            f"文案服务没有返回完整文案，当前只拿到{transcript_candidate_label(short_candidate)}"
        )
    raise RuntimeError(f"transcript_task_timeout: {truncate_text(last_response)}")


def save_transcript_for_video(conn, row, log=None):
    video_url = canonical_video_url(row["share_url"] or row["source_url"])
    if not video_url:
        raise RuntimeError("video_link_missing")
    transcript_result = fetch_transcript_from_transcriptgenerate(video_url, log=log)
    ts = now()
    has_transcript, transcript_length = transcript_meta(transcript_result["transcript_text"])
    conn.execute(
        """
        UPDATE videos
        SET transcript_text = %s, transcript_source = %s, transcript_created_at = %s,
            has_transcript = %s, transcript_length = %s,
            status = 'transcript_saved', updated_at = %s
        WHERE id = %s
        """,
        (
            transcript_result["transcript_text"],
            f"TranscriptGenerate/task:{transcript_result['task_id']}",
            ts,
            has_transcript,
            transcript_length,
            ts,
            row["id"],
        ),
    )
    updated = conn.execute("SELECT * FROM videos WHERE id = %s", (row["id"],)).fetchone()
    return row_to_video(updated), transcript_result


def process_pending_queue(conn, limit=1, delay_seconds=0, log=None):
    limit = max(1, min(int(limit or 1), 20))
    processed = []
    failed = []
    stopped = False
    for index in range(limit):
        if queue_cancel_requested():
            stopped = True
            if log:
                log("队列已暂停，不再继续处理下一条")
            break
        row = conn.execute(
            """
            SELECT v.*, COUNT(c.id) AS claim_count
            FROM videos v
            LEFT JOIN claims c ON c.video_id = v.id AND c.deleted_at IS NULL
            WHERE v.status IN ('transcript_pending', 'transcript_saved', 'created', 'transcript_failed')
              AND v.deleted_at IS NULL
              AND COALESCE(v.retry_count, 0) < 3
            GROUP BY v.id
            HAVING (COALESCE(v.has_transcript, false) = false OR (COALESCE(v.has_transcript, false) = true AND COUNT(c.id) = 0))
            ORDER BY v.published_at_ts DESC NULLS LAST, v.created_at DESC
            LIMIT 1
            """
        ).fetchone()
        if not row:
            break
        item = {"video_id": row["id"], "title": row["title"], "stage": "started"}
        current = row
        try:
            conn.execute(
                """
                UPDATE videos
                SET retry_count = COALESCE(retry_count, 0) + 1,
                    last_retry_at = %s, last_error = NULL, updated_at = %s
                WHERE id = %s
                """,
                (now(), now(), row["id"]),
            )
            if log:
                log(f"{index + 1}/{limit} 开始处理视频：{row['title']}")
            if not row["has_transcript"]:
                item["stage"] = "transcript"
                if log:
                    log(f"{index + 1}/{limit} 正在向文案服务提交视频链接...")
                video, transcript_result = save_transcript_for_video(conn, row, log=log)
                item["transcript_task_id"] = transcript_result["task_id"]
                current = conn.execute("SELECT * FROM videos WHERE id = %s", (video["id"],)).fetchone()
                if log:
                    log(f"{index + 1}/{limit} 文案成功，长度 {len(video['transcript_text'] or '')}")
            if int(current["transcript_length"] or 0) < MIN_TRANSCRIPT_LENGTH:
                item["stage"] = "skipped"
                item["error"] = f"文案过短，长度 {int(current['transcript_length'] or 0)}"
                conn.execute(
                    "UPDATE videos SET status = 'transcript_failed', last_error = %s, updated_at = %s WHERE id = %s",
                    (item["error"], now(), row["id"]),
                )
                conn.commit()
                failed.append(item)
                if log:
                    log(f"{index + 1}/{limit} 跳过：{item['error']}")
                continue
            item["stage"] = "claims"
            if log:
                log(f"{index + 1}/{limit} 正在分析文案并提取装修观点...")
            result = extract_claims_for_video(conn, row_to_video(current))
            item["claim_count"] = len(result.get("claims") or [])
            result_status = result.get("status")
            if result_status == "completed":
                item["stage"] = "completed"
                processed.append(item)
                if log:
                    log(f"{index + 1}/{limit} 处理完成，新增观点 {item['claim_count']} 条")
            elif result_status == "filtered":
                item["stage"] = "filtered"
                item["message"] = result.get("message") or "无有效内容"
                processed.append(item)
                if log:
                    log(f"{index + 1}/{limit} 无有效内容：模型未提取到通用装修观点")
            else:
                item["stage"] = "failed"
                item["error"] = result.get("message") or result_status or "观点提取失败"
                conn.execute(
                    "UPDATE videos SET status = %s, last_error = %s, updated_at = %s WHERE id = %s",
                    (video_status_for_processing_error(current), item["error"], now(), row["id"]),
                )
                conn.commit()
                failed.append(item)
                if log:
                    log(f"{index + 1}/{limit} 观点提取失败：{item['error']}")
        except Exception as exc:
            item["stage"] = "failed"
            item["error"] = truncate_error(str(exc))
            conn.execute(
                "UPDATE videos SET status = %s, last_error = %s, updated_at = %s WHERE id = %s",
                (video_status_for_processing_error(current), item["error"], now(), row["id"]),
            )
            conn.commit()
            failed.append(item)
            if log:
                log(f"{index + 1}/{limit} 失败：{item['error']}")
        if index < limit - 1 and delay_seconds > 0:
            if queue_cancel_requested():
                stopped = True
                if log:
                    log("队列已暂停，不再等待下一条")
                break
            if log:
                log(f"等待 {int(delay_seconds)} 秒后处理下一条...")
            deadline = time.time() + delay_seconds
            while time.time() < deadline:
                if queue_cancel_requested():
                    stopped = True
                    if log:
                        log("队列已暂停，不再继续处理下一条")
                    break
                time.sleep(min(1, max(0, deadline - time.time())))
            if stopped:
                break
    remaining = conn.execute(
        """
        SELECT COUNT(*) AS count
        FROM videos v
        LEFT JOIN claims c ON c.video_id = v.id AND c.deleted_at IS NULL
        WHERE v.status IN ('transcript_pending', 'transcript_saved', 'created', 'transcript_failed')
          AND v.deleted_at IS NULL
          AND COALESCE(v.retry_count, 0) < 3
        GROUP BY v.id
        HAVING (COALESCE(v.has_transcript, false) = false OR (COALESCE(v.has_transcript, false) = true AND COUNT(c.id) = 0))
        """
    ).fetchall()
    return {
        "status": "cancelled" if stopped else "completed",
        "processed": processed,
        "failed": failed,
        "remaining": len(remaining),
    }


def retry_video_from_transcript(video_id, log=None):
    with video_process_lock(video_id), connect() as conn:
        row = conn.execute("SELECT * FROM videos WHERE id = %s AND deleted_at IS NULL", (video_id,)).fetchone()
        if not row:
            raise RuntimeError("video not found")
        if log:
            log(f"{video_id} {row['title']} 从获取文案开始重试")
        conn.execute(
            """
            UPDATE videos
            SET transcript_text = NULL, transcript_source = NULL, transcript_created_at = NULL,
                has_transcript = false, transcript_length = 0,
                retry_count = COALESCE(retry_count, 0) + 1,
                last_retry_at = %s, last_error = NULL,
                status = 'transcript_pending', updated_at = %s
            WHERE id = %s
            """,
            (now(), now(), video_id),
        )
        row = conn.execute("SELECT * FROM videos WHERE id = %s AND deleted_at IS NULL", (video_id,)).fetchone()
        if log:
            log(f"{video_id} 拉取文案中...")
        video, transcript_result = save_transcript_for_video(conn, row, log=log)
        transcript_len = int(video["transcript_length"] or 0)
        if log:
            log(f"{video_id} 文案成功，长度 {transcript_len}")
        if transcript_len < MIN_TRANSCRIPT_LENGTH:
            conn.execute(
                """
                UPDATE videos
                SET status = 'transcript_failed', last_error = %s, updated_at = %s
                WHERE id = %s
                """,
                (f"文案过短，长度 {transcript_len}", now(), video_id),
            )
            raise RuntimeError(f"文案过短，长度 {transcript_len}")
        if log:
            log(f"{video_id} DeepSeek 提取观点中...")
        conn.execute(
            "UPDATE claims SET deleted_at = %s, deleted_by = %s, delete_reason = %s WHERE video_id = %s AND deleted_at IS NULL",
            (now(), "system", "retry_full", video_id),
        )
        result = extract_claims_for_video(conn, video)
        if result.get("status") not in ("completed", "filtered"):
            raise RuntimeError(result.get("message") or result.get("status") or "观点提取失败")
        if result.get("status") == "completed":
            conn.execute("UPDATE videos SET last_error = NULL, updated_at = %s WHERE id = %s", (now(), video_id))
        if log:
            if result.get("status") == "filtered":
                log(f"{video_id} 无有效内容：模型未提取到通用装修观点")
            else:
                log(f"{video_id} 完成，观点 {len(result.get('claims') or [])} 条")
        return result


def run_queue_job(limit, delay_seconds, job_id=None):
    job_id = job_id or f"job_{time.strftime('%Y%m%d_%H%M%S')}"
    with QUEUE_JOB_LOCK:
        QUEUE_JOB.update(
            {
                "job_id": job_id,
                "running": True,
                "logs": [],
                "processed": [],
                "failed": [],
                "remaining": None,
                "started_at": now(),
                "finished_at": None,
                "cancel_requested": False,
            }
        )
    queue_log(f"自动队列开始，本次目标 {limit} 条，间隔 {int(delay_seconds)} 秒")
    try:
        with connect() as conn:
            skipped_retry_rows = conn.execute(
                """
                SELECT id, title, retry_count FROM videos
                WHERE status IN ('transcript_pending', 'transcript_saved', 'created', 'transcript_failed')
                  AND deleted_at IS NULL
                  AND COALESCE(retry_count, 0) >= 3
                  AND (COALESCE(has_transcript, false) = false OR id NOT IN (SELECT DISTINCT video_id FROM claims WHERE deleted_at IS NULL))
                ORDER BY published_at_ts DESC NULLS LAST, created_at DESC
                """
            ).fetchall()
            for row in skipped_retry_rows:
                queue_log(f"跳过 {row['id']}：已重试 {row['retry_count']} 次，需要人工确认")
            result = process_pending_queue(conn, limit=limit, delay_seconds=delay_seconds, log=queue_log)
        with QUEUE_JOB_LOCK:
            QUEUE_JOB["processed"] = result["processed"]
            QUEUE_JOB["failed"] = result["failed"]
            QUEUE_JOB["remaining"] = result["remaining"]
        if result.get("status") == "cancelled":
            queue_log(f"队列已暂停，成功 {len(result['processed'])} 条，失败 {len(result['failed'])} 条，剩余 {result['remaining']} 条")
        else:
            queue_log(f"自动队列结束，成功 {len(result['processed'])} 条，失败 {len(result['failed'])} 条，剩余 {result['remaining']} 条")
    except Exception as exc:
        queue_log(f"自动队列异常：{truncate_error(str(exc))}")
    finally:
        with QUEUE_JOB_LOCK:
            QUEUE_JOB["running"] = False
            QUEUE_JOB["finished_at"] = now()


def run_video_retry_job(video_id, job_id=None):
    job_id = job_id or f"job_{time.strftime('%Y%m%d_%H%M%S')}"
    with QUEUE_JOB_LOCK:
        QUEUE_JOB.update(
            {
                "job_id": job_id,
                "running": True,
                "logs": [],
                "processed": [],
                "failed": [],
                "remaining": None,
                "started_at": now(),
                "finished_at": None,
                "cancel_requested": False,
            }
        )
    queue_log(f"单条重试开始：{video_id}")
    item = {"video_id": video_id, "stage": "started"}
    try:
        result = retry_video_from_transcript(video_id, log=queue_log)
        item["stage"] = "filtered" if result.get("status") == "filtered" else "completed"
        item["claim_count"] = len(result.get("claims") or [])
        with QUEUE_JOB_LOCK:
            QUEUE_JOB["processed"] = [item]
            QUEUE_JOB["failed"] = []
            QUEUE_JOB["remaining"] = None
        if result.get("status") == "filtered":
            queue_log("单条重试结束，无有效内容")
        else:
            queue_log(f"单条重试结束，成功 1 条，观点 {item['claim_count']} 条")
    except Exception as exc:
        item["stage"] = "failed"
        item["error"] = truncate_error(str(exc))
        try:
            with connect() as conn:
                row = conn.execute("SELECT * FROM videos WHERE id = %s AND deleted_at IS NULL", (video_id,)).fetchone()
                conn.execute(
                    "UPDATE videos SET status = %s, last_error = %s, updated_at = %s WHERE id = %s",
                    (video_status_for_processing_error(row), item["error"], now(), video_id),
                )
        except Exception:
            pass
        with QUEUE_JOB_LOCK:
            QUEUE_JOB["processed"] = []
            QUEUE_JOB["failed"] = [item]
            QUEUE_JOB["remaining"] = None
        queue_log(f"单条重试失败：{item['error']}")
    finally:
        with QUEUE_JOB_LOCK:
            QUEUE_JOB["running"] = False
            QUEUE_JOB["finished_at"] = now()


def insert_claims(conn, video, run_id, claims):
    conn.execute(
        "UPDATE claims SET deleted_at = %s, deleted_by = %s, delete_reason = %s WHERE video_id = %s AND deleted_at IS NULL",
        (now(), "system", "replace_extracted_claims", video["id"]),
    )
    inserted = []
    for claim in claims:
        claim_id = new_id("claim")
        item = {
            "id": claim_id,
            "video_id": video["id"],
            "extraction_run_id": run_id,
            "object_name": claim.get("object_name") or "未提及",
            "stance": claim.get("stance") or "未明确",
            "process_stage": claim.get("process_stage") or "待人工分类",
            "space_tags": claim.get("space_tags") or ["未提及"],
            "topic_tags": claim.get("topic_tags") or ["未提及"],
            "original_conclusion": claim.get("original_conclusion") or "未提及",
            "original_reasons": claim.get("original_reasons") or [],
            "conditions": claim.get("conditions") or "未提及",
            "alternatives": claim.get("alternatives") or [],
            "price_info": claim.get("price_info") or "未提及",
            "source_video_url": claim.get("source_video_url") or video["source_url"],
            "created_at": now(),
        }
        conn.execute(
            """
            INSERT INTO claims (
              id, video_id, extraction_run_id, object_name, stance, process_stage,
              space_tags, topic_tags, original_conclusion, original_reasons,
              conditions, alternatives, price_info, source_video_url, created_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                item["id"],
                item["video_id"],
                item["extraction_run_id"],
                item["object_name"],
                item["stance"],
                item["process_stage"],
                jsonb_value(item["space_tags"], []),
                jsonb_value(item["topic_tags"], []),
                item["original_conclusion"],
                jsonb_value(item["original_reasons"], []),
                item["conditions"],
                jsonb_value(item["alternatives"], []),
                item["price_info"],
                item["source_video_url"],
                item["created_at"],
            ),
        )
        inserted.append(item)
    return inserted


def extract_claims_for_video(conn, video):
    with video_process_lock(video["id"]):
        return extract_claims_for_video_locked(conn, video)


def extract_claims_for_video_locked(conn, video):
    if not video["transcript_text"]:
        raise ValueError("transcript_text is empty")
    transcript_length = int(video.get("transcript_length") or len((video.get("transcript_text") or "").strip()))
    if transcript_length < MIN_TRANSCRIPT_LENGTH:
        filtered_message = FILTER_REASON_MESSAGES["duplicate_or_too_thin"]
        detail_message = f"{filtered_message}，当前长度 {transcript_length}"
        conn.execute(
            "UPDATE videos SET status = 'claims_filtered', last_error = %s, updated_at = %s WHERE id = %s",
            (detail_message, now(), video["id"]),
        )
        return {
            "run_id": None,
            "status": "filtered",
            "claims": [],
            "dropped_claims": [{"reason": "duplicate_or_too_thin"}],
            "message": detail_message,
        }

    prompt = build_extract_prompt(video)
    input_hash = hashlib.sha256(video["transcript_text"].encode("utf-8")).hexdigest()
    run_id = new_id("run")
    raw_response, error = call_deepseek(prompt)
    status = "completed" if raw_response else error
    conn.execute(
        """
        INSERT INTO extraction_runs (
          id, video_id, model, prompt_version, input_hash, prompt_text,
          raw_response_json, status, error_message, created_at
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            run_id,
            video["id"],
            DEEPSEEK_MODEL,
            PROMPT_VERSION,
            input_hash,
            prompt,
            raw_response_jsonb(raw_response),
            status,
            error,
            now(),
        ),
    )
    if error:
        error_message = truncate_error(error)
        conn.execute(
            "UPDATE videos SET status = %s, last_error = %s, updated_at = %s WHERE id = %s",
            (video_status_for_processing_error(video), error_message, now(), video["id"]),
        )
        return {
            "run_id": run_id,
            "status": status,
            "model": DEEPSEEK_MODEL,
            "prompt_version": PROMPT_VERSION,
            "input_hash": input_hash,
            "message": error_message,
        }

    try:
        extracted = parse_deepseek_content(raw_response)
    except ValueError as exc:
        error_message = truncate_error(str(exc))
        conn.execute(
            "UPDATE extraction_runs SET status = %s, error_message = %s WHERE id = %s",
            ("parse_failed", error_message, run_id),
        )
        conn.execute(
            "UPDATE videos SET status = %s, last_error = %s, updated_at = %s WHERE id = %s",
            (video_status_for_processing_error(video), error_message, now(), video["id"]),
        )
        raise
    sanitized_claims, dropped_claims = sanitize_claims(extracted.get("claims", []))
    claims = insert_claims(conn, video, run_id, sanitized_claims)
    if claims:
        conn.execute(
            "UPDATE videos SET status = 'claims_extracted', last_error = NULL, updated_at = %s WHERE id = %s",
            (now(), video["id"]),
        )
        return {"run_id": run_id, "status": "completed", "claims": claims, "dropped_claims": dropped_claims}

    filtered_message = build_filtered_message(extracted, dropped_claims)
    conn.execute(
        "UPDATE videos SET status = 'claims_filtered', last_error = %s, updated_at = %s WHERE id = %s",
        (filtered_message, now(), video["id"]),
    )
    return {
        "run_id": run_id,
        "status": "filtered",
        "claims": [],
        "dropped_claims": dropped_claims,
        "message": filtered_message,
    }


def build_video_filters(query):
    clauses = ["v.deleted_at IS NULL"]
    params = []
    source_id = (query.get("source_id") or [""])[0].strip()
    platform = (query.get("platform") or [""])[0].strip()
    creator = (query.get("creator") or [""])[0].strip()
    q = (query.get("q") or [""])[0].strip()
    if source_id:
        clauses.append("v.source_id = %s")
        params.append(source_id)
    if platform and platform != "全部":
        clauses.append("v.platform = %s")
        params.append(platform)
    if creator and creator != "全部":
        clauses.append("v.creator = %s")
        params.append(creator)
    if q:
        clauses.append("(COALESCE(v.title, '') || ' ' || COALESCE(v.creator, '') || ' ' || COALESCE(v.platform, '') ILIKE %s)")
        params.append(f"%{q}%")
    return clauses, params


def fetch_video_page(conn, query=None, limit=DEFAULT_VIDEO_LIMIT, offset=0):
    query = query or {}
    clauses, params = build_video_filters(query)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    total = conn.execute(f"SELECT COUNT(*) AS count FROM videos v {where}", params).fetchone()["count"]
    rows = conn.execute(
        f"""
        WITH page_videos AS (
          SELECT
            v.id, v.source_id, v.platform, v.creator, v.title, v.source_url,
            v.share_url, v.share_text, v.published_at,
            v.has_transcript, v.transcript_length,
            v.transcript_source, v.transcript_created_at,
            v.retry_count, v.last_retry_at, v.last_error, v.status,
            v.created_at, v.updated_at, v.published_at_ts
          FROM videos v
          {where}
          ORDER BY v.published_at_ts DESC NULLS LAST, v.created_at DESC, v.id DESC
          LIMIT %s OFFSET %s
        ),
        claim_counts AS (
          SELECT c.video_id, COUNT(*) AS claim_count
          FROM claims c
          JOIN page_videos pv ON pv.id = c.video_id
          WHERE c.deleted_at IS NULL
          GROUP BY c.video_id
        )
        SELECT
          v.id, v.source_id, v.platform, v.creator, v.title, v.source_url,
          v.share_url, v.share_text, v.published_at,
          COALESCE(v.has_transcript, false) AS has_transcript,
          COALESCE(v.transcript_length, 0) AS transcript_length,
          v.transcript_source, v.transcript_created_at,
          v.retry_count, v.last_retry_at, v.last_error, v.status,
          v.created_at, v.updated_at,
          COALESCE(cc.claim_count, 0) AS claim_count
        FROM page_videos v
        LEFT JOIN claim_counts cc ON cc.video_id = v.id
        ORDER BY v.published_at_ts DESC NULLS LAST, v.created_at DESC, v.id DESC
        """,
        [*params, limit, offset],
    ).fetchall()
    return {
        "videos": [row_to_video_summary(row) for row in rows],
        "total": int(total or 0),
        "limit": limit,
        "offset": offset,
        "has_more": offset + len(rows) < int(total or 0),
    }


def progress_state_sql():
    return """
      CASE
        WHEN v.status = 'transcript_failed' OR COALESCE(v.last_error, '') != '' THEN '失败'
        WHEN v.status = 'claims_filtered' THEN '已完成'
        WHEN COALESCE(v.source_url, '') = '' AND COALESCE(v.share_url, '') = '' THEN '缺链接'
        WHEN COALESCE(cc.claim_count, 0) > 0 THEN '已完成'
        WHEN COALESCE(v.has_transcript, false) THEN '待观点'
        ELSE '待文案'
      END
    """


def fetch_progress_video_page(conn, query=None, limit=DEFAULT_VIDEO_LIMIT, offset=0):
    query = query or {}
    state = (query.get("state") or ["全部"])[0].strip() or "全部"
    clauses = []
    params = []
    if state != "全部":
        clauses.append("state = %s")
        params.append(state)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    state_expr = progress_state_sql()
    base_sql = f"""
        WITH claim_counts AS (
          SELECT video_id, COUNT(*) AS claim_count
          FROM claims
          WHERE deleted_at IS NULL
          GROUP BY video_id
        ),
        progress_videos AS (
          SELECT
            v.id, v.source_id, v.platform, v.creator, v.title, v.source_url,
            v.share_url, v.share_text, v.published_at,
            COALESCE(v.has_transcript, false) AS has_transcript,
            COALESCE(v.transcript_length, 0) AS transcript_length,
            v.transcript_source, v.transcript_created_at,
            v.retry_count, v.last_retry_at, v.last_error, v.status,
            v.created_at, v.updated_at, v.published_at_ts,
            COALESCE(cc.claim_count, 0) AS claim_count,
            {state_expr} AS state
          FROM videos v
          LEFT JOIN claim_counts cc ON cc.video_id = v.id
          WHERE v.deleted_at IS NULL
        )
    """
    total = conn.execute(f"{base_sql} SELECT COUNT(*) AS count FROM progress_videos {where}", params).fetchone()["count"]
    rows = conn.execute(
        f"""
        {base_sql}
        SELECT *
        FROM progress_videos
        {where}
        ORDER BY published_at_ts DESC NULLS LAST, created_at DESC, id DESC
        LIMIT %s OFFSET %s
        """,
        [*params, limit, offset],
    ).fetchall()
    return {
        "videos": [row_to_video_summary(row) for row in rows],
        "total": int(total or 0),
        "limit": limit,
        "offset": offset,
        "has_more": offset + len(rows) < int(total or 0),
    }


def fetch_progress_summary(conn):
    rows = conn.execute(
        f"""
        WITH claim_counts AS (
          SELECT video_id, COUNT(*) AS claim_count
          FROM claims
          WHERE deleted_at IS NULL
          GROUP BY video_id
        ),
        states AS (
          SELECT
            {progress_state_sql()} AS state
          FROM videos v
          LEFT JOIN claim_counts cc ON cc.video_id = v.id
          WHERE v.deleted_at IS NULL
        )
        SELECT state, COUNT(*) AS count
        FROM states
        GROUP BY state
        """
    ).fetchall()
    counts = {"全部": 0, "缺链接": 0, "待文案": 0, "待观点": 0, "已完成": 0, "失败": 0}
    for row in rows:
        state = row["state"]
        count = int(row["count"] or 0)
        counts[state] = count
        counts["全部"] += count
    return counts


def build_bootstrap_payload(conn):
    video_page = fetch_video_page(conn, limit=DEFAULT_VIDEO_LIMIT, offset=0)
    source_stats_rows = conn.execute(
        """
        SELECT
          v.source_id,
          COUNT(DISTINCT v.id) AS video_count,
          COUNT(DISTINCT v.id) FILTER (WHERE v.status = 'transcript_pending') AS pending_count,
          COUNT(c.id) AS claim_count
        FROM videos v
        LEFT JOIN claims c ON c.video_id = v.id AND c.deleted_at IS NULL
        WHERE v.source_id IS NOT NULL AND v.deleted_at IS NULL
        GROUP BY v.source_id
        """
    ).fetchall()
    source_stats = {row["source_id"]: dict(row) for row in source_stats_rows}

    source_rows = []
    if source_stats:
        source_rows = conn.execute(
            """
            SELECT *
            FROM sources
            WHERE id = ANY(%s)
            ORDER BY
              CASE priority WHEN 'P0' THEN 0 WHEN 'P1' THEN 1 ELSE 2 END,
              created_at DESC
            """,
            (list(source_stats.keys()),),
        ).fetchall()
    sources = []
    for row in source_rows:
        item = dict(row)
        item.update(source_stats.get(row["id"], {"video_count": 0, "claim_count": 0, "pending_count": 0}))
        sources.append(row_to_source(item))

    stats_row = conn.execute(
        """
        SELECT
          COUNT(*) AS video_count,
          COUNT(*) FILTER (WHERE COALESCE(has_transcript, false)) AS transcript_count
        FROM videos
        WHERE deleted_at IS NULL
        """
    ).fetchone()
    claim_count = conn.execute("SELECT COUNT(*) AS count FROM claims WHERE deleted_at IS NULL").fetchone()["count"]

    return {
        "health": {
            "ok": True,
            "db": "postgresql",
            "db_available": DB_STATUS["available"],
            "db_message": DB_STATUS["message"],
            "model": DEEPSEEK_MODEL,
        },
        "sources": sources,
        "videos": video_page["videos"],
        "videos_page": {
            "total": video_page["total"],
            "limit": video_page["limit"],
            "offset": video_page["offset"],
            "has_more": video_page["has_more"],
        },
        "knowledge": {"claims": [], "deferred": True},
        "stats": {
            "source_count": len(sources),
            "video_count": int(stats_row["video_count"] or 0),
            "transcript_count": int(stats_row["transcript_count"] or 0),
            "claim_count": int(claim_count or 0),
        },
    }


def get_cached_bootstrap_payload(conn):
    current_time = time.time()
    with BOOTSTRAP_CACHE_LOCK:
        cached_payload = BOOTSTRAP_CACHE["payload"]
        if cached_payload is not None and current_time - BOOTSTRAP_CACHE["timestamp"] < BOOTSTRAP_CACHE_TTL_SECONDS:
            return cached_payload

    payload = build_bootstrap_payload(conn)
    with BOOTSTRAP_CACHE_LOCK:
        BOOTSTRAP_CACHE["timestamp"] = time.time()
        BOOTSTRAP_CACHE["payload"] = payload
    return payload


def invalidate_bootstrap_cache():
    with BOOTSTRAP_CACHE_LOCK:
        BOOTSTRAP_CACHE["timestamp"] = 0
        BOOTSTRAP_CACHE["payload"] = None


class AppHandler(SimpleHTTPRequestHandler):
    extensions_map = {
        **SimpleHTTPRequestHandler.extensions_map,
        ".js": "application/javascript",
        ".css": "text/css",
        ".html": "text/html",
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC_ROOT or ROOT), **kwargs)

    def end_headers(self):
        headers = getattr(self, "headers", None)
        origin = headers.get("Origin") if headers else None
        self.send_header("Access-Control-Allow-Origin", origin or "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.send_header("Access-Control-Allow-Credentials", "true")
        self.send_header("Vary", "Origin")
        if not getattr(self, "path", "").startswith("/api/"):
            self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(204)
        self.end_headers()

    def send_json(self, payload, status=200):
        body = json_dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_error_json(self, status, message):
        self.send_json({"error": message}, status=status)

    def do_GET(self):
        parsed = urlparse(self.path)
        if not parsed.path.startswith("/api/"):
            if STATIC_ROOT:
                for header in ("If-Modified-Since", "If-None-Match"):
                    if header in self.headers:
                        del self.headers[header]
                return super().do_GET()
            return self.send_error_json(404, "api server only")
        try:
            return self.handle_get(parsed)
        except Exception:
            traceback.print_exc()
            return self.send_error_json(500, "internal server error")

    def do_POST(self):
        parsed = urlparse(self.path)
        if not parsed.path.startswith("/api/"):
            return self.send_error_json(404, "not found")
        try:
            return self.handle_post(parsed)
        except ValueError as exc:
            return self.send_error_json(400, str(exc))
        except Exception:
            traceback.print_exc()
            return self.send_error_json(500, "internal server error")

    def do_DELETE(self):
        parsed = urlparse(self.path)
        if not parsed.path.startswith("/api/"):
            return self.send_error_json(404, "not found")
        try:
            return self.handle_delete(parsed)
        except Exception:
            traceback.print_exc()
            return self.send_error_json(500, "internal server error")

    def handle_get(self, parsed):
        path = parsed.path
        query = parse_qs(parsed.query)
        if path == "/api/health":
            return self.send_json(
                {
                    "ok": True,
                    "db": "postgresql",
                    "db_available": DB_STATUS["available"],
                    "db_message": DB_STATUS["message"],
                    "model": DEEPSEEK_MODEL,
                }
            )

        if path == "/api/admin/session":
            return self.send_json(admin_session_payload(self))

        if path == "/api/douyin/login-status":
            snapshot = douyin_login_snapshot()
            if snapshot.get("running"):
                return self.send_json(snapshot)
            try:
                status = get_douyin_login_status()
            except RuntimeError as exc:
                return self.send_json(
                    {
                        **snapshot,
                        "status": "unknown",
                        "message": truncate_error(str(exc)),
                        "logged_in": False,
                    }
                )
            with DOUYIN_LOGIN_LOCK:
                DOUYIN_LOGIN_JOB.update(
                    {
                        "status": "logged_in" if status.get("logged_in") else "missing",
                        "message": "抖音登录态有效。" if status.get("logged_in") else "未检测到有效抖音登录态。",
                        "logged_in": bool(status.get("logged_in")),
                        "cookie_count": int(status.get("cookie_count") or 0),
                        "valid_cookie_names": status.get("valid_cookie_names") or [],
                    }
                )
            return self.send_json(douyin_login_snapshot())

        if not DB_STATUS["available"]:
            return self.send_error_json(503, f"database unavailable: {truncate_error(DB_STATUS['message'])}")

        if path == "/api/bootstrap":
            with BOOTSTRAP_CACHE_LOCK:
                cached_payload = BOOTSTRAP_CACHE["payload"]
                if cached_payload is not None and time.time() - BOOTSTRAP_CACHE["timestamp"] < BOOTSTRAP_CACHE_TTL_SECONDS:
                    return self.send_json(cached_payload)
            with connect() as conn:
                return self.send_json(get_cached_bootstrap_payload(conn))

        with connect() as conn:
            if path == "/api/admin/deleted":
                if not require_admin(self):
                    return
                limit = query_int(query, "limit", 50, minimum=1, maximum=MAX_PAGE_LIMIT)
                offset = query_int(query, "offset", 0, minimum=0)
                video_rows = conn.execute(
                    """
                    SELECT id, platform, creator, title, source_url, deleted_at, deleted_by, delete_reason, updated_at
                    FROM videos
                    WHERE deleted_at IS NOT NULL
                    ORDER BY deleted_at DESC, id DESC
                    LIMIT %s OFFSET %s
                    """,
                    (limit, offset),
                ).fetchall()
                claim_rows = conn.execute(
                    """
                    SELECT c.id, c.video_id, c.object_name, c.original_conclusion, c.deleted_at, c.deleted_by, c.delete_reason,
                           v.title AS video_title, v.deleted_at AS video_deleted_at
                    FROM claims c
                    LEFT JOIN videos v ON v.id = c.video_id
                    WHERE c.deleted_at IS NOT NULL
                    ORDER BY c.deleted_at DESC, c.id DESC
                    LIMIT %s OFFSET %s
                    """,
                    (limit, offset),
                ).fetchall()
                video_total = conn.execute("SELECT COUNT(*) AS count FROM videos WHERE deleted_at IS NOT NULL").fetchone()["count"]
                claim_total = conn.execute("SELECT COUNT(*) AS count FROM claims WHERE deleted_at IS NOT NULL").fetchone()["count"]
                return self.send_json(
                    {
                        "videos": [dict(row) for row in video_rows],
                        "claims": [dict(row) for row in claim_rows],
                        "video_total": int(video_total or 0),
                        "claim_total": int(claim_total or 0),
                        "limit": limit,
                        "offset": offset,
                        "has_more": offset + max(len(video_rows), len(claim_rows)) < max(int(video_total or 0), int(claim_total or 0)),
                    }
                )

            if path == "/api/sources":
                rows = conn.execute(
                    """
                    WITH source_video_counts AS (
                      SELECT
                        source_id,
                        COUNT(*) AS video_count,
                        COUNT(*) FILTER (WHERE status = 'transcript_pending') AS pending_count
                      FROM videos
                      WHERE deleted_at IS NULL
                      GROUP BY source_id
                    ),
                    source_claim_counts AS (
                      SELECT v.source_id, COUNT(c.id) AS claim_count
                      FROM videos v
                      JOIN claims c ON c.video_id = v.id AND c.deleted_at IS NULL
                      WHERE v.deleted_at IS NULL
                      GROUP BY v.source_id
                    )
                    SELECT
                      s.*,
                      COALESCE(svc.video_count, 0) AS video_count,
                      COALESCE(scc.claim_count, 0) AS claim_count,
                      COALESCE(svc.pending_count, 0) AS pending_count
                    FROM sources s
                    JOIN source_video_counts svc ON svc.source_id = s.id
                    LEFT JOIN source_claim_counts scc ON scc.source_id = s.id
                    ORDER BY
                      CASE s.priority WHEN 'P0' THEN 0 WHEN 'P1' THEN 1 ELSE 2 END,
                      s.created_at DESC
                    """
                ).fetchall()
                return self.send_json({"sources": [row_to_source(row) for row in rows]})

            if path == "/api/videos":
                limit = query_int(query, "limit", DEFAULT_VIDEO_LIMIT, minimum=1, maximum=MAX_PAGE_LIMIT)
                offset = query_int(query, "offset", 0, minimum=0)
                return self.send_json(fetch_video_page(conn, query=query, limit=limit, offset=offset))

            if path == "/api/progress-summary":
                return self.send_json({"counts": fetch_progress_summary(conn)})

            if path == "/api/progress-videos":
                limit = query_int(query, "limit", DEFAULT_VIDEO_LIMIT, minimum=1, maximum=MAX_PAGE_LIMIT)
                offset = query_int(query, "offset", 0, minimum=0)
                return self.send_json(fetch_progress_video_page(conn, query=query, limit=limit, offset=offset))

            if path.startswith("/api/videos/"):
                video_id = path.split("/")[3]
                row = conn.execute("SELECT * FROM videos WHERE id = %s AND deleted_at IS NULL", (video_id,)).fetchone()
                if not row:
                    return self.send_error_json(404, "video not found")
                claims = conn.execute("SELECT * FROM claims WHERE video_id = %s AND deleted_at IS NULL ORDER BY created_at", (video_id,)).fetchall()
                response = {
                    "video": row_to_video(row),
                    "claims": [row_to_claim(item) for item in claims],
                }
                if (query.get("include_runs") or [""])[0] == "1":
                    runs = conn.execute(
                        "SELECT * FROM extraction_runs WHERE video_id = %s ORDER BY created_at DESC",
                        (video_id,),
                    ).fetchall()
                    response["extraction_runs"] = [dict(item) for item in runs]
                return self.send_json(response)

            if path == "/api/knowledge":
                clauses = ["deleted_at IS NULL"]
                params = []
                stage = (query.get("stage") or [""])[0]
                stages = [item.strip() for item in (query.get("stages") or [""])[0].split(",") if item.strip()]
                tag = (query.get("tag") or [""])[0]
                q = (query.get("q") or [""])[0]
                limit = query_int(query, "limit", DEFAULT_KNOWLEDGE_LIMIT, minimum=1, maximum=MAX_PAGE_LIMIT)
                offset = query_int(query, "offset", 0, minimum=0)
                if stages:
                    clauses.append("process_stage = ANY(%s)")
                    params.append(stages)
                elif stage:
                    clauses.append("process_stage = %s")
                    params.append(stage)
                if tag:
                    clauses.append("(space_tags ? %s OR topic_tags ? %s OR stance = %s)")
                    params.extend([tag, tag, tag])
                if q:
                    clauses.append(
                        "(COALESCE(object_name, '') || ' ' || COALESCE(original_conclusion, '') || ' ' || COALESCE(conditions, '') || ' ' || COALESCE(original_reasons::text, '') ILIKE %s)"
                    )
                    params.append(f"%{q}%")
                where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
                total = conn.execute(f"SELECT COUNT(*) AS count FROM claims {where}", params).fetchone()["count"]
                rows = conn.execute(
                    f"SELECT * FROM claims {where} ORDER BY created_at DESC, id DESC LIMIT %s OFFSET %s",
                    [*params, limit, offset],
                ).fetchall()
                return self.send_json(
                    {
                        "claims": [row_to_claim(row) for row in rows],
                        "total": int(total or 0),
                        "limit": limit,
                        "offset": offset,
                        "has_more": offset + len(rows) < int(total or 0),
                    }
                )

            if path == "/api/queue/next":
                transcript_row = conn.execute(
                    """
                    SELECT v.*, COUNT(c.id) AS claim_count
                    FROM videos v
                    LEFT JOIN claims c ON c.video_id = v.id AND c.deleted_at IS NULL
                    WHERE v.status = 'transcript_saved' AND v.deleted_at IS NULL
                    GROUP BY v.id
                    HAVING COUNT(c.id) = 0
                    ORDER BY v.published_at_ts DESC NULLS LAST, v.created_at DESC
                    LIMIT 1
                    """
                ).fetchone()
                pending_row = conn.execute(
                    """
                    SELECT v.*, COUNT(c.id) AS claim_count
                    FROM videos v
                    LEFT JOIN claims c ON c.video_id = v.id AND c.deleted_at IS NULL
                    WHERE v.status = 'transcript_pending' AND v.deleted_at IS NULL
                    GROUP BY v.id
                    ORDER BY v.published_at_ts DESC NULLS LAST, v.created_at DESC
                    LIMIT 1
                    """
                ).fetchone()
                return self.send_json(
                    {
                        "next_extract": row_to_video(transcript_row) if transcript_row else None,
                        "next_transcript": row_to_video(pending_row) if pending_row else None,
                    }
                )

            if path == "/api/queue/status":
                return self.send_json(queue_snapshot())

        return self.send_error_json(404, "not found")

    def handle_post(self, parsed):
        path = parsed.path
        payload = read_json(self)
        if path == "/api/admin/login":
            if not ADMIN_PASSWORD:
                return self.send_error_json(503, "admin password is not configured")
            password = str(payload.get("password") or "")
            if not hmac.compare_digest(password, ADMIN_PASSWORD):
                return self.send_error_json(401, "invalid admin password")
            session_value = make_admin_session_value()
            cookie = (
                f"{ADMIN_SESSION_COOKIE}={session_value}; Max-Age={ADMIN_SESSION_MAX_AGE_SECONDS}; "
                "Path=/; HttpOnly; SameSite=Lax"
            )
            self.send_response(200)
            self.send_header("Set-Cookie", cookie)
            body = json_dumps(admin_session_payload(self) | {"authenticated": True}).encode("utf-8")
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if path == "/api/admin/logout":
            self.send_response(200)
            self.send_header("Set-Cookie", f"{ADMIN_SESSION_COOKIE}=; Max-Age=0; Path=/; HttpOnly; SameSite=Lax")
            body = json_dumps({"authenticated": False, "configured": bool(ADMIN_PASSWORD)}).encode("utf-8")
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if path == "/api/douyin/login/start":
            snapshot = douyin_login_snapshot()
            if snapshot.get("running"):
                return self.send_json(snapshot, status=202)
            profile_url = (payload.get("profile_url") or "https://www.douyin.com/").strip()
            wait_seconds = max(30, min(int(payload.get("wait_seconds") or 180), 600))
            thread = threading.Thread(target=run_douyin_login_job, args=(profile_url, wait_seconds), daemon=True)
            thread.start()
            time.sleep(0.1)
            return self.send_json(douyin_login_snapshot(), status=202)

        if not DB_STATUS["available"]:
            return self.send_error_json(503, f"database unavailable: {truncate_error(DB_STATUS['message'])}")

        invalidate_bootstrap_cache()

        with connect() as conn:
            if path == "/api/sources":
                require_fields(payload, ["platform", "name"])
                source_id = payload.get("id") or new_id("src")
                conn.execute(
                    """
                    INSERT INTO sources (id, platform, name, profile_url, priority, status, notes, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT(id) DO UPDATE SET
                      platform=excluded.platform,
                      name=excluded.name,
                      profile_url=excluded.profile_url,
                      priority=excluded.priority,
                      status=excluded.status,
                      notes=excluded.notes
                    """,
                    (
                        source_id,
                        payload["platform"],
                        payload["name"],
                        payload.get("profile_url"),
                        payload.get("priority", "P1"),
                        payload.get("status", "active"),
                        payload.get("notes", ""),
                        now(),
                    ),
                )
                return self.send_json({"id": source_id}, status=201)

            if path == "/api/videos":
                require_fields(payload, ["platform", "creator", "title", "source_url"])
                video_id = payload.get("id") or new_id("vid")
                ts = now()
                published_at = payload.get("published_at")
                published_at_ts = parse_published_at(published_at)
                has_transcript, transcript_length = transcript_meta(payload.get("transcript_text"))
                conn.execute(
                    """
                    INSERT INTO videos (
                      id, source_id, platform, creator, title, source_url, share_url, share_text, published_at, published_at_ts,
                      transcript_text, transcript_source, transcript_created_at,
                      has_transcript, transcript_length, status, created_at, updated_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT(source_url) DO UPDATE SET
                      title=excluded.title,
                      platform=excluded.platform,
                      creator=excluded.creator,
                      share_url=excluded.share_url,
                      share_text=excluded.share_text,
                      published_at=excluded.published_at,
                      published_at_ts=excluded.published_at_ts,
                      deleted_at=NULL,
                      deleted_by=NULL,
                      delete_reason=NULL,
                      updated_at=excluded.updated_at
                    """,
                    (
                        video_id,
                        payload.get("source_id"),
                        payload["platform"],
                        payload["creator"],
                        payload["title"],
                        payload["source_url"],
                        payload.get("share_url"),
                        payload.get("share_text"),
                        published_at,
                        published_at_ts,
                        payload.get("transcript_text"),
                        payload.get("transcript_source"),
                        ts if has_transcript else None,
                        has_transcript,
                        transcript_length,
                        "transcript_saved" if has_transcript else "created",
                        ts,
                        ts,
                    ),
                )
                row = conn.execute("SELECT * FROM videos WHERE source_url = %s AND deleted_at IS NULL", (payload["source_url"],)).fetchone()
                return self.send_json({"video": row_to_video(row)}, status=201)

            if path == "/api/videos/batch-collect":
                require_fields(payload, ["platform", "creator", "profile_url"])
                items = payload.get("videos") or []
                if not isinstance(items, list) or not items:
                    raise ValueError("missing videos")
                return self.send_json(save_collected_videos(conn, payload, items), status=201)

            if path == "/api/videos/quick-ingest":
                share_text = (payload.get("share_text") or "").strip()
                share_url = canonical_video_url(payload.get("share_url") or extract_first_url(share_text))
                if not share_url:
                    raise ValueError("missing share_text or share_url")

                fallback_transcript = (payload.get("transcript_text") or "").strip()
                transcript_source = (payload.get("transcript_source") or "").strip() or "manual"
                if fallback_transcript:
                    transcript_result = {
                        "task_id": "provided_transcript",
                        "transcript_text": fallback_transcript,
                        "raw_result": {"source": transcript_source},
                    }
                else:
                    try:
                        transcript_result = fetch_transcript_from_transcriptgenerate(share_url)
                    except RuntimeError as exc:
                        return self.send_error_json(502, truncate_error(str(exc)))
                transcript_text = transcript_result["transcript_text"]
                has_transcript, transcript_length = transcript_meta(transcript_text)
                ts = now()
                video_id = payload.get("id") or new_id("vid")
                existing = conn.execute("SELECT * FROM videos WHERE source_url = %s", (share_url,)).fetchone()
                platform = payload.get("platform") or (existing["platform"] if existing else None) or infer_platform(share_url)
                title = payload.get("title") or (existing["title"] if existing else None) or infer_title(share_text, transcript_text)
                creator = payload.get("creator") or (existing["creator"] if existing else None) or "待识别"
                published_at = payload.get("published_at") or (existing["published_at"] if existing else None)
                published_at_ts = parse_published_at(published_at)
                conn.execute(
                    """
                    INSERT INTO videos (
                      id, source_id, platform, creator, title, source_url, share_url, share_text, published_at, published_at_ts,
                      transcript_text, transcript_source, transcript_created_at,
                      has_transcript, transcript_length, status, created_at, updated_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT(source_url) DO UPDATE SET
                      title=excluded.title,
                      platform=excluded.platform,
                      creator=excluded.creator,
                      share_url=excluded.share_url,
                      share_text=excluded.share_text,
                      published_at=COALESCE(excluded.published_at, videos.published_at),
                      published_at_ts=COALESCE(excluded.published_at_ts, videos.published_at_ts),
                      transcript_text=excluded.transcript_text,
                      transcript_source=excluded.transcript_source,
                      transcript_created_at=excluded.transcript_created_at,
                      has_transcript=excluded.has_transcript,
                      transcript_length=excluded.transcript_length,
                      status=excluded.status,
                      deleted_at=NULL,
                      deleted_by=NULL,
                      delete_reason=NULL,
                      updated_at=excluded.updated_at
                    """,
                    (
                        video_id,
                        payload.get("source_id") or (existing["source_id"] if existing else None),
                        platform,
                        creator,
                        title,
                        share_url,
                        share_url,
                        share_text,
                        published_at,
                        published_at_ts,
                        transcript_text,
                        transcript_source if fallback_transcript else f"TranscriptGenerate/task:{transcript_result['task_id']}",
                        ts,
                        has_transcript,
                        transcript_length,
                        "transcript_saved",
                        ts,
                        ts,
                    ),
                )
                row = conn.execute("SELECT * FROM videos WHERE source_url = %s AND deleted_at IS NULL", (share_url,)).fetchone()
                video = row_to_video(row)
                response = {
                    "video": video,
                    "transcript": {
                        "task_id": transcript_result["task_id"],
                        "transcript_text": transcript_text,
                        "raw_result": transcript_result["raw_result"],
                    },
                }
                if payload.get("extract"):
                    response["extraction"] = extract_claims_for_video(conn, video)
                    refreshed = conn.execute("SELECT * FROM videos WHERE id = %s", (video["id"],)).fetchone()
                    response["video"] = row_to_video(refreshed)
                return self.send_json(response, status=201)

            if path.startswith("/api/videos/") and path.endswith("/transcript"):
                video_id = path.split("/")[3]
                require_fields(payload, ["transcript_text"])
                row = conn.execute("SELECT * FROM videos WHERE id = %s AND deleted_at IS NULL", (video_id,)).fetchone()
                if not row:
                    return self.send_error_json(404, "video not found")
                conn.execute(
                    """
                    UPDATE videos
                    SET transcript_text = %s, transcript_source = %s, transcript_created_at = %s,
                        has_transcript = %s, transcript_length = %s,
                        status = 'transcript_saved', updated_at = %s
                    WHERE id = %s
                    """,
                    (
                        payload["transcript_text"],
                        payload.get("transcript_source", "manual"),
                        now(),
                        *transcript_meta(payload["transcript_text"]),
                        now(),
                        video_id,
                    ),
                )
                updated = conn.execute("SELECT * FROM videos WHERE id = %s", (video_id,)).fetchone()
                return self.send_json({"video": row_to_video(updated)})

            if path.startswith("/api/videos/") and path.endswith("/restore"):
                if not require_admin(self):
                    return
                video_id = path.split("/")[3]
                row = conn.execute("SELECT id FROM videos WHERE id = %s AND deleted_at IS NOT NULL", (video_id,)).fetchone()
                if not row:
                    return self.send_error_json(404, "deleted video not found")
                conn.execute(
                    """
                    UPDATE videos
                    SET deleted_at = NULL, deleted_by = NULL, delete_reason = NULL, updated_at = %s
                    WHERE id = %s
                    """,
                    (now(), video_id),
                )
                restored = conn.execute("SELECT * FROM videos WHERE id = %s", (video_id,)).fetchone()
                invalidate_bootstrap_cache()
                return self.send_json({"status": "restored", "video": row_to_video(restored)})

            if path.startswith("/api/videos/") and path.endswith("/transcript/retry"):
                video_id = path.split("/")[3]
                row = conn.execute("SELECT * FROM videos WHERE id = %s AND deleted_at IS NULL", (video_id,)).fetchone()
                if not row:
                    return self.send_error_json(404, "video not found")
                try:
                    video, transcript_result = save_transcript_for_video(conn, row)
                except RuntimeError as exc:
                    return self.send_error_json(502, truncate_error(str(exc)))
                return self.send_json(
                    {
                        "video": video,
                        "transcript": {
                            "task_id": transcript_result["task_id"],
                            "transcript_text": transcript_result["transcript_text"],
                            "raw_result": transcript_result["raw_result"],
                        },
                    }
                )

            if path.startswith("/api/videos/") and path.endswith("/share"):
                video_id = path.split("/")[3]
                row = conn.execute("SELECT * FROM videos WHERE id = %s AND deleted_at IS NULL", (video_id,)).fetchone()
                if not row:
                    return self.send_error_json(404, "video not found")
                conn.execute(
                    """
                    UPDATE videos
                    SET share_url = %s, share_text = %s, updated_at = %s
                    WHERE id = %s
                    """,
                    (
                        payload.get("share_url"),
                        payload.get("share_text"),
                        now(),
                        video_id,
                    ),
                )
                updated = conn.execute("SELECT * FROM videos WHERE id = %s", (video_id,)).fetchone()
                return self.send_json({"video": row_to_video(updated)})

            if path.startswith("/api/videos/") and path.endswith("/extract"):
                video_id = path.split("/")[3]
                row = conn.execute("SELECT * FROM videos WHERE id = %s AND deleted_at IS NULL", (video_id,)).fetchone()
                if not row:
                    return self.send_error_json(404, "video not found")
                video = row_to_video(row)
                try:
                    result = extract_claims_for_video(conn, video)
                except ValueError as exc:
                    return self.send_error_json(409, str(exc))
                return self.send_json(result, status=202 if result["status"] != "completed" else 200)

            if path.startswith("/api/claims/") and path.endswith("/restore"):
                if not require_admin(self):
                    return
                claim_id = path.split("/")[3]
                row = conn.execute(
                    """
                    SELECT c.id, c.video_id
                    FROM claims c
                    JOIN videos v ON v.id = c.video_id
                    WHERE c.id = %s AND c.deleted_at IS NOT NULL AND v.deleted_at IS NULL
                    """,
                    (claim_id,),
                ).fetchone()
                if not row:
                    return self.send_error_json(404, "deleted claim not found or video is deleted")
                conn.execute(
                    """
                    UPDATE claims
                    SET deleted_at = NULL, deleted_by = NULL, delete_reason = NULL
                    WHERE id = %s
                    """,
                    (claim_id,),
                )
                conn.execute("UPDATE videos SET updated_at = %s WHERE id = %s", (now(), row["video_id"]))
                restored = conn.execute("SELECT * FROM claims WHERE id = %s", (claim_id,)).fetchone()
                invalidate_bootstrap_cache()
                return self.send_json({"status": "restored", "claim": row_to_claim(restored)})

            if path.startswith("/api/videos/") and path.endswith("/retry-full/start"):
                video_id = path.split("/")[3]
                row = conn.execute("SELECT id, retry_count FROM videos WHERE id = %s AND deleted_at IS NULL", (video_id,)).fetchone()
                if not row:
                    return self.send_error_json(404, "video not found")
                if int(row["retry_count"] or 0) >= 3 and not payload.get("force"):
                    return self.send_error_json(409, "retry_confirmation_required")
                job_id = reserve_queue_job()
                if not job_id:
                    return self.send_json(queue_snapshot(), status=409)
                thread = threading.Thread(target=run_video_retry_job, args=(video_id, job_id), daemon=True)
                thread.start()
                time.sleep(0.1)
                return self.send_json(queue_snapshot(), status=202)

            if path == "/api/queue/extract-next":
                row = conn.execute(
                    """
                    SELECT v.*, COUNT(c.id) AS claim_count
                    FROM videos v
                    LEFT JOIN claims c ON c.video_id = v.id AND c.deleted_at IS NULL
                    WHERE v.status = 'transcript_saved' AND v.deleted_at IS NULL
                    GROUP BY v.id
                    HAVING COUNT(c.id) = 0
                    ORDER BY v.published_at_ts DESC NULLS LAST, v.created_at DESC
                    LIMIT 1
                    """
                ).fetchone()
                if not row:
                    return self.send_json({"status": "empty", "message": "no transcript_saved videos waiting for extraction"})
                video = row_to_video(row)
                result = extract_claims_for_video(conn, video)
                refreshed = conn.execute("SELECT * FROM videos WHERE id = %s AND deleted_at IS NULL", (video["id"],)).fetchone()
                result["video"] = row_to_video(refreshed)
                return self.send_json(result, status=202 if result["status"] != "completed" else 200)

            if path == "/api/queue/process-pending":
                limit = int(payload.get("limit") or 1)
                delay_seconds = float(payload.get("delay_seconds", TRANSCRIPT_QUEUE_DELAY_SECONDS))
                result = process_pending_queue(conn, limit=limit, delay_seconds=delay_seconds)
                return self.send_json(result)

            if path == "/api/queue/start":
                job_id = reserve_queue_job()
                if not job_id:
                    return self.send_json(queue_snapshot(), status=409)
                limit = int(payload.get("limit") or AUTO_QUEUE_BATCH_LIMIT)
                delay_seconds = float(payload.get("delay_seconds", TRANSCRIPT_QUEUE_DELAY_SECONDS))
                thread = threading.Thread(target=run_queue_job, args=(limit, delay_seconds, job_id), daemon=True)
                thread.start()
                time.sleep(0.1)
                return self.send_json(queue_snapshot(), status=202)

            if path == "/api/queue/cancel":
                requested = request_queue_cancel()
                return self.send_json(queue_snapshot(), status=202 if requested else 200)

            if path.startswith("/api/sources/") and path.endswith("/update"):
                source_id = path.split("/")[3]
                row = conn.execute("SELECT * FROM sources WHERE id = %s", (source_id,)).fetchone()
                if not row:
                    return self.send_error_json(404, "source not found")
                limit = int(payload.get("limit") or 5)
                if "douyin" not in (row["platform"] or "").lower() and "抖音" not in (row["platform"] or ""):
                    return self.send_error_json(400, "collector_only_supports_douyin_now")
                try:
                    collected = collect_douyin_profile(row["profile_url"], limit, creator=row["name"])
                except RuntimeError as exc:
                    return self.send_error_json(502, truncate_error(str(exc)))
                result = save_collected_videos(
                    conn,
                    {
                        "source_id": row["id"],
                        "platform": row["platform"],
                        "creator": row["name"],
                        "profile_url": row["profile_url"],
                        "priority": row["priority"],
                        "limit": limit,
                        "notes": row["notes"] or "",
                    },
                    collected,
                )
                result["status"] = "completed"
                result["message"] = (
                    f"采集完成：保存 {result['stats']['saved']} 条，新增 {result['stats']['created']} 条，重复 {result['stats']['duplicate']} 条。"
                )
                return self.send_json(result, status=201)

            if path == "/api/sources/update-all":
                rows = conn.execute("SELECT id FROM sources WHERE status = 'active' ORDER BY priority, created_at DESC").fetchall()
                return self.send_json(
                    {
                        "status": "collector_not_ready",
                        "limit": int(payload.get("limit") or 5),
                        "sources": [row["id"] for row in rows],
                        "message": "本地浏览器采集器尚未接入；下一步会串行更新所有博主。",
                    },
                    status=202,
                )

        return self.send_error_json(404, "not found")

    def handle_delete(self, parsed):
        path = parsed.path
        if not DB_STATUS["available"]:
            return self.send_error_json(503, f"database unavailable: {truncate_error(DB_STATUS['message'])}")
        if not require_admin(self):
            return
        deleted_at = now()
        delete_reason = (parse_qs(parsed.query).get("reason") or [""])[0].strip()
        with connect() as conn:
            if path.startswith("/api/videos/"):
                video_id = path.split("/")[3]
                row = conn.execute("SELECT id FROM videos WHERE id = %s AND deleted_at IS NULL", (video_id,)).fetchone()
                if not row:
                    return self.send_error_json(404, "video not found")
                conn.execute(
                    """
                    UPDATE claims
                    SET deleted_at = %s, deleted_by = %s, delete_reason = %s
                    WHERE video_id = %s AND deleted_at IS NULL
                    """,
                    (deleted_at, "admin", delete_reason, video_id),
                )
                conn.execute(
                    """
                    UPDATE videos
                    SET deleted_at = %s, deleted_by = %s, delete_reason = %s, updated_at = %s
                    WHERE id = %s AND deleted_at IS NULL
                    """,
                    (deleted_at, "admin", delete_reason, deleted_at, video_id),
                )
                invalidate_bootstrap_cache()
                return self.send_json({"status": "deleted", "video_id": video_id})

            if path.startswith("/api/claims/"):
                claim_id = path.split("/")[3]
                row = conn.execute("SELECT id, video_id FROM claims WHERE id = %s AND deleted_at IS NULL", (claim_id,)).fetchone()
                if not row:
                    return self.send_error_json(404, "claim not found")
                conn.execute(
                    """
                    UPDATE claims
                    SET deleted_at = %s, deleted_by = %s, delete_reason = %s
                    WHERE id = %s AND deleted_at IS NULL
                    """,
                    (deleted_at, "admin", delete_reason, claim_id),
                )
                conn.execute("UPDATE videos SET updated_at = %s WHERE id = %s", (deleted_at, row["video_id"]))
                invalidate_bootstrap_cache()
                return self.send_json({"status": "deleted", "claim_id": claim_id, "video_id": row["video_id"]})

        return self.send_error_json(404, "not found")


def main():
    if check_database():
        print("PostgreSQL connection OK")
    else:
        print(f"PostgreSQL connection failed: {DB_STATUS['message']}", file=sys.stderr)
    port = int(sys.argv[1]) if len(sys.argv) >= 2 else int(os.environ.get("PORT", "4180"))
    server = ThreadingHTTPServer(("127.0.0.1", port), AppHandler)
    print(f"Serving API on http://127.0.0.1:{port}")
    if STATIC_ROOT:
        print(f"Serving static files from {STATIC_ROOT}")
    server.serve_forever()


if __name__ == "__main__":
    main()
