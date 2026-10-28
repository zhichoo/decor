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
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
import advertising
from collector_douyin import is_pinned_video
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
        os.environ.setdefault(str(key), json.dumps(value) if isinstance(value, (dict, list)) else str(value))


load_local_config()

PROMPT_VERSION = "extract_claims_v5_grounded_written"
DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-flash")
DEEPSEEK_BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_GROUP = os.environ.get("DEEPSEEK_GROUP", "").strip()
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "").strip()
PUBLIC_READ_ONLY = os.environ.get("PUBLIC_READ_ONLY", "false").strip().lower() in ("1", "true", "yes")
ADMIN_SESSION_COOKIE = "decor_admin_session"
ADMIN_SESSION_MAX_AGE_SECONDS = int(os.environ.get("ADMIN_SESSION_MAX_AGE_SECONDS", str(7 * 24 * 60 * 60)))
MAX_ERROR_MESSAGE_LENGTH = 2000
MAX_TRANSCRIPT_DEBUG_LENGTH = 1500
TRANSCRIPT_PROVIDER = os.environ.get("TRANSCRIPT_PROVIDER", "transcriptgenerate").strip()
TRANSCRIPT_SETTINGS_PATH = Path(os.environ.get("TRANSCRIPT_SETTINGS_PATH", ROOT / "transcription-settings.local.json"))
TRANSCRIPT_SETTINGS_LOCK = threading.RLock()
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
TRANSCRIPT_POLL_INTERVAL_SECONDS = max(1, float(os.environ.get("TRANSCRIPT_POLL_INTERVAL_SECONDS", "4")))
TRANSCRIPT_MAX_POLLS = max(1, int(os.environ.get("TRANSCRIPT_MAX_POLLS", "150")))
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
    if PUBLIC_READ_ONLY:
        return False
    cookies = parse_cookie_header(handler.headers.get("Cookie", ""))
    return validate_admin_session_value(cookies.get(ADMIN_SESSION_COOKIE))


def admin_session_payload(handler):
    authenticated = is_admin_request(handler)
    return {
        "authenticated": authenticated,
        "configured": bool(ADMIN_PASSWORD),
        "read_only": PUBLIC_READ_ONLY,
        "max_age": ADMIN_SESSION_MAX_AGE_SECONDS,
    }


def require_admin(handler):
    if PUBLIC_READ_ONLY:
        handler.send_error_json(403, "public instance is read-only")
        return False
    if not ADMIN_PASSWORD:
        handler.send_error_json(503, "admin password is not configured")
        return False
    if not is_admin_request(handler):
        handler.send_error_json(401, "admin login required")
        return False
    return True


PUBLIC_POST_PATHS = frozenset({"/api/admin/login", "/api/admin/logout"})


def is_admin_operation_path(path):
    # New write endpoints are private unless explicitly made public.
    return path.startswith("/api/") and path not in PUBLIC_POST_PATHS


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

    @contextmanager
    def transaction(self):
        if not self._conn.autocommit:
            raise RuntimeError("nested database transaction")
        self._conn.autocommit = False
        try:
            yield
            self._conn.commit()
        except BaseException:
            self._conn.rollback()
            raise
        finally:
            self._conn.autocommit = True

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
        "ad_review": advertising.current_review(row),
        "has_transcript": bool(row.get("has_transcript", has_transcript)),
        "transcript_length": int(row.get("transcript_length", transcript_length) or 0),
        "transcript_source": row["transcript_source"],
        "transcript_job": {key: value for key, value in (row.get("transcript_job") or {}).items()
                           if key in ("provider", "state", "task_id")},
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
        "ad_review": advertising.current_review(row),
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


def database_readiness():
    try:
        with connect() as conn:
            ready = conn.execute("""
                SELECT to_regclass('public.sources') IS NOT NULL
                   AND to_regclass('public.videos') IS NOT NULL
                   AND to_regclass('public.claims') IS NOT NULL
                   AND to_regclass('public.extraction_runs') IS NOT NULL
                   AND EXISTS (SELECT 1 FROM information_schema.columns
                               WHERE table_schema='public' AND table_name='videos'
                                 AND column_name='transcript_job' AND data_type='jsonb') AS ready
            """).fetchone()["ready"]
        return bool(ready), "" if ready else "数据库尚未初始化或文案任务迁移未完成"
    except Exception:
        return False, "数据库暂不可用"


def row_to_claim(row, source_video=None):
    return {
        "id": row["id"],
        "video_id": row["video_id"],
        "source_video_is_promotional": bool(source_video and advertising.current_review(source_video).get("decision") == "advertising"),
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


def claims_with_source_labels(conn, rows):
    if not rows:
        return []
    sources = conn.execute(
        "SELECT id, title, transcript_text, ad_review, ad_review_override FROM videos WHERE id = ANY(%s)",
        (list({row["video_id"] for row in rows}),),
    ).fetchall()
    by_id = {row["id"]: row for row in sources}
    return [row_to_claim(row, source_video=by_id.get(row["video_id"])) for row in rows]


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
                    "original_conclusion": "non-empty complete written Chinese conclusion supported by transcript",
                    "original_reasons": ["string"],
                    "conditions": "string or 未提及",
                    "alternatives": ["string"],
                    "price_info": "string or 未提及",
                    "source_video_url": "string",
                    "source_quotes": ["1 to 3 verbatim continuous quotes supporting the conclusion and details"],
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
                    "original_reasons": ["不泡够时间，上墙以后容易空鼓脱落"],
                    "conditions": "适用于吸水率高的瓷砖",
                    "alternatives": [],
                    "price_info": "未提及",
                    "source_video_url": "",
                    "source_quotes": ["吸水率高的砖要泡够两小时，不然上墙以后容易空鼓脱落"],
                },
                {
                    "object_name": "瓷砖留缝",
                    "stance": "明确推荐",
                    "process_stage": "瓦工阶段",
                    "space_tags": ["未提及"],
                    "topic_tags": ["材料"],
                    "original_conclusion": "留缝不能小于2毫米，用十字卡控制间距",
                    "original_reasons": [],
                    "conditions": "未提及",
                    "alternatives": [],
                    "price_info": "未提及",
                    "source_video_url": "",
                    "source_quotes": ["铺完之后留缝不能小于2毫米，用十字卡控制间距"],
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

    written_example = {
        "input": "家人们我跟你说，厨房双层碗篮才不到四百块钱，比做抽屉还便宜呢。分类一目了然，碗筷不用摞在一起，是不是？",
        "output": {
            "video_summary": {"title": "示例", "source_url": "", "platform": "", "creator": "", "main_topics": ["厨房收纳"]},
            "filter_reason": "none", "filter_message": "",
            "claims": [{
                "object_name": "厨房双层碗篮", "stance": "价格建议", "process_stage": "待人工分类",
                "space_tags": ["厨房"], "topic_tags": ["未提及"],
                "original_conclusion": "双层碗篮可分类收纳碗筷，案例价格低于抽屉做法。",
                "original_reasons": ["碗筷分类清楚，无需叠放。"], "conditions": "未提及",
                "alternatives": [], "price_info": "不到四百元", "source_video_url": "",
                "source_quotes": ["厨房双层碗篮才不到四百块钱，比做抽屉还便宜呢。", "分类一目了然，碗筷不用摞在一起"]
            }]
        }
    }

    return f"""你是装修视频文案结构化提取器。

核心规则：
1. 只能依据输入文案原文提取信息，禁止补充、推断、扩写、改写为新建议。
2. 原文没有明确说到的信息，字段填写"未提及"或空数组。
3. 原文有多个装修对象时，拆成多条 claims。
4. 原文有价格、条件、替代做法时，分别放入对应字段。
5. process_stage 和 tags 只能从给定分类中选择；如果无法可靠归类，process_stage 填"待人工分类"，标签填"未提及"。
6. 原文有明确对象和可理解的实用观点、选择建议、做法或功能，即使只有一条、没有数字参数，也可提取；仅有“买好的”“真解乏”等空泛评价时不生成卡片。
7. 产品内容优先提炼选择重点、功能和指标；作者明确推荐某品牌时可保留为该作者的建议，但不得补出品牌优势或改写成普遍保证。
8. 只有商品名称、型号或价格列表，没有明确建议、用途或功能说明的广告口播，直接跳过。
9. 不要输出解释，不要输出 Markdown，只输出 JSON 对象。第一个字符必须是 {{，最后一个字符必须是 }}。
10. 文案来自语音识别，可能存在同音字或谐音错误（例如"空鼓"误识别为"空古"，"腻子"误识别为"泥子"）。请根据上下文语义理解原意进行提取；若某段文字因识别错误导致语义不可判断，对应字段填"未提及"，不生成错误观点。
11. 先判断文案是否值得提取：如果整体是纯推广、促销、带货、进群、抢购、优惠券、粉丝福利、价格引流、联系方式引流，且没有通用装修知识或产品选购重点，claims 必须为空，filter_reason 填 promotion_only。
12. 如果文案口语化严重、断句混乱、语音识别错乱、关键对象和结论无法可靠还原，claims 必须为空，filter_reason 填 speech_unclear，不要猜测或补写观点。
13. 仅有生活感叹、展示、价格活动且没有明确实用观点时，claims 必须为空，filter_reason 填 no_general_knowledge。
14. 只有品牌、型号、系列、单品名称或价格列表，没有作者明确建议或功能说明时，claims 必须为空，filter_reason 填 brand_model_only。
15. 如果只是展示装修案例、效果、风格、生活方式，没有明确可复用做法或选购指标，claims 必须为空，filter_reason 填 case_showcase_only。
16. 对象或结论不完整、无法可靠理解时，claims 必须为空，filter_reason 填 duplicate_or_too_thin；不要仅因普通口语、建议简短或与其他卡部分重复而过滤。
17. 有可提取观点时，filter_reason 填 none，filter_message 填空字符串；无观点时，claims 必须为空，filter_message 用一句中文说明过滤原因。
18. 卡片用简洁、完整的书面中文，忠实概括原意，删除我/你/咱们、我跟你说、家人们、对不对、是不是、啊、呀等对话与口头禅，以及点赞关注、情绪化感叹、夸张比喻。不要整段复制口播。只有“买好的”“真舒服”“真解乏”“很实用”“性价比高”，没有具体做法/指标/条件的，舍弃。
19. 每张卡须有明确对象和完整结论，结论不能是“未提及”。标题/简介/标签只能帮助识别对象，不能代替视频文案作为知识依据。
20. 每张卡必须提供 source_quotes，包含1至3段从下方文案逐字复制的连续原句，直接支撑结论、原因和条件；引用中不修正错别字、不插入省略号、不自行拼接。没有可靠原句则舍弃。source_quotes保留口语，其他字段写清楚、简洁的书面中文。
21. 同音字仅在原意明确时理解，不确定的材料/品牌/尺寸/单价直接省略，不能靠常识补全，例如不能把“750x150”猜成“750x1500”。不得补充原文未说的因果机制、品牌、替代品或价格。数字尽量沿用文案表达。
22. 返回前逐卡核对：推荐方向和适用条件不能反转，原文“不选花纹”不能变成“要有花纹”，建议不能改成必然保证。只保留有依据的知识卡，不为了凑数量生成占位卡。
23. source_quotes 中保留原文的重复、口头禅和识别错词；可选更短的连续原句，但不得拼接、省略中间文字或润色证据。
24. source_quotes 之外的所有字段必须使用简洁书面语，尤其 original_reasons，不可复制口播段落。把“真解乏得劲儿”整理为“休息舒适、缓解疲劳”；把“往屁股上崩马桶水”整理为“水花飞溅”；删除“内行人的选择”等身份宣传。只有原文引句 source_quotes 保留口语原貌。
25. 不得把作者的一次使用体验扩大为普遍禁忌或追加新建议。例如原文只说自家推拉门不常关闭，可记录“不常关闭时利用率低”，不得加“选择更简单方式”；原文只说极简风格显乱，不得编造“适合高度自律的家庭”。conditions 没有明确依据时填“未提及”。
26. 原文的态度、范围和疑问要保留，缺少原因就 original_reasons=[]，不要替作者解释。输出前逐个检查结论、理由、条件和价格，删除任何没有引句支持的新增信息。

去口头禅示例（保留有依据的具体信息）：
输入文案：{written_example["input"]}
期望输出：{json_dumps(written_example["output"])}

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
        normalize_text_value(claim.get("stance")),
        normalize_text_value(claim.get("object_name")),
        normalize_text_value(claim.get("original_conclusion")),
        normalize_text_value(claim.get("conditions")),
        normalize_text_value(claim.get("price_info")),
        " ".join(normalize_list_value(claim.get("original_reasons"))),
        " ".join(normalize_list_value(claim.get("alternatives"))),
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


def evidence_text(value):
    # Ignore punctuation/spacing, but never silently repair words in an evidence quote.
    return re.sub(r"[\W_]+", "", str(value or ""), flags=re.UNICODE).lower()


def numeric_evidence_values(text):
    from decimal import Decimal

    values = {Decimal(value) for value in re.findall(r"\d+(?:\.\d+)?", str(text or ""))}
    digits = {char: index for index, char in enumerate("零一二三四五六七八九")}
    digits.update({"〇": 0, "两": 2})
    units = {"十": 10, "百": 100, "千": 1000, "万": 10000, "亿": 100000000}
    measure = r"(?:元|块|钱|毫米|厘米|公分|米|小时|分钟|秒|平|月|年|天|层|个|条|扇|级|瓦|升|成)"
    pattern = r"[零〇一二两三四五六七八九十百千万亿]+(?:点[零〇一二三四五六七八九]+)?"
    for match in re.finditer(pattern, str(text or "")):
        token = match.group()
        if len(token) == 1 and not re.match(measure, str(text or "")[match.end():]):
            continue
        integer, _, fraction = token.partition("点")
        if len(integer) > 1 and not any(char in units for char in integer) and not fraction:
            continue
        if any(integer[index] in digits and integer[index + 1] in digits
               and integer[index] not in "零〇" for index in range(len(integer) - 1)):
            continue
        if len(integer) > 1 and integer[-1] in digits and integer[-2] in "百千万亿":
            continue
        total = section = number = 0
        for char in integer:
            if char in digits:
                number = digits[char]
            else:
                unit = units[char]
                if unit < 10000:
                    section += (number or 1) * unit
                elif unit == 10000:
                    total += (section + number) * unit
                    section = 0
                else:
                    total = (total + section + number) * unit
                    section = 0
                number = 0
        value = Decimal(total + section + number)
        if fraction:
            value += Decimal('0.' + ''.join(str(digits[char]) for char in fraction))
        values.add(value)
    return values


def claim_quality_error(claim, transcript_text=None, require_evidence=False):
    for name in ("object_name", "original_conclusion", "conditions", "price_info"):
        if name in claim and not isinstance(claim[name], (str, type(None))):
            return "invalid_claim_field"
    for name in ("original_reasons", "alternatives", "space_tags", "topic_tags"):
        if name in claim and (not isinstance(claim[name], list) or any(not isinstance(x, str) for x in claim[name])):
            return "invalid_claim_field"
    conclusion = normalize_text_value(claim.get("original_conclusion"))
    if conclusion in ("", "未提及", "未明确", "无", "不详"):
        return "empty_conclusion"
    if not normalize_text_value(claim.get("object_name")) or claim.get("object_name") == "未提及":
        return "empty_object"
    body = " ".join([conclusion, *normalize_list_value(claim.get("original_reasons")), normalize_text_value(claim.get("conditions"))])
    speech_markers = re.findall(r"我跟你说|我告诉你|家人们|兄弟们|老铁们?|是不是啊|对不对啊|听懂了吗|点赞关注|关注我|你懂的|咱们说实话", body)
    if len(speech_markers) >= 2 or re.search(r"点赞.{0,8}关注|关注.{0,8}点赞|打赏支持", body):
        return "speech_unclear"
    if require_evidence and re.search(
        r"我跟你说|家人们|宝子们|老铁们|懂的都懂|绝绝子|真解乏|得劲儿?|"
        r"内行人.{0,6}选择|乱七八糟玩意|往屁股上|像[个]?囚笼|成了.{0,4}保姆|媳妇说|咱们",
        body,
    ):
        return "colloquial_card_text"
    if require_evidence:
        quotes = claim.get("source_quotes")
        if not isinstance(quotes, list) or not quotes or len(quotes) > 3 or any(not isinstance(q, str) for q in quotes):
            return "missing_source_evidence"
        source = evidence_text(transcript_text)
        if any(len(evidence_text(q)) < 6 or evidence_text(q) not in source for q in quotes):
            return "unsupported_source_evidence"
        detail = " ".join([body, normalize_text_value(claim.get("price_info")), *normalize_list_value(claim.get("alternatives"))])
        source_numbers = numeric_evidence_values(transcript_text)
        if not numeric_evidence_values(detail).issubset(source_numbers):
            return "unsupported_numeric_detail"
    return None


def sanitize_claims(claims, transcript_text=None, require_evidence=False):
    filtered = []
    dropped = []
    for claim in claims or []:
        if not isinstance(claim, dict):
            dropped.append({"reason": "invalid_claim_type"})
            continue
        quality_error = claim_quality_error(claim, transcript_text, require_evidence)
        if quality_error:
            dropped.append({"reason": quality_error, "object_name": claim.get("object_name")})
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


def deepseek_int_setting(name, default, minimum, maximum):
    try:
        value = int(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


def deepseek_timeout_seconds():
    return deepseek_int_setting("DEEPSEEK_TIMEOUT_SECONDS", 300, 30, 600)


def deepseek_transient_error(error):
    text = (error or "").lower()
    status = re.search(r"deepseek_http_(\d{3})", text)
    if status:
        return int(status.group(1)) == 429 or 500 <= int(status.group(1)) <= 599
    # A timeout or a broken response can occur after the provider accepted and
    # billed the request. Leave those retries to the user; automatically retry
    # only explicit temporary HTTP failures or failures before connecting.
    return any(marker in text for marker in (
        "curl_exit_5:", "curl_exit_6:", "curl_exit_7:",
        "connection refused", "name resolution", "name or service not known",
        "nodename nor servname", "no route to host",
    ))


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
    if DEEPSEEK_MODEL.lower() == "deepseek-flash" or DEEPSEEK_MODEL.lower().startswith("deepseek-v4"):
        thinking = os.environ.get("DEEPSEEK_THINKING", "disabled").strip().lower()
        payload["thinking"] = {"type": "enabled" if thinking == "enabled" else "disabled"}
        if thinking == "enabled":
            effort = os.environ.get("DEEPSEEK_REASONING_EFFORT", "low").strip().lower()
            payload["reasoning_effort"] = effort if effort in ("low", "high", "max") else "low"
        token_limit = os.environ.get("DEEPSEEK_MAX_OUTPUT_TOKENS", "8192").strip()
        payload["max_tokens"] = max(1024, min(32768, int(token_limit))) if token_limit.isdigit() else 8192
    if DEEPSEEK_GROUP and urlparse(DEEPSEEK_BASE_URL).hostname != "api.deepseek.com":
        payload["group"] = DEEPSEEK_GROUP
    base_url = DEEPSEEK_BASE_URL.rstrip("/")
    url = f"{base_url}/chat/completions"
    retries = deepseek_int_setting("DEEPSEEK_MAX_RETRIES", 1, 0, 2)
    error = None
    for attempt in range(retries + 1):
        response, error = deepseek_request_once(url, payload, api_key)
        if "deepseek_http_404" in (error or "") and url == f"{base_url}/chat/completions" and not base_url.endswith("/v1"):
            url = f"{base_url}/v1/chat/completions"
            response, error = deepseek_request_once(url, payload, api_key)
        if response is not None and response.strip():
            return normalize_deepseek_response(response), None
        error = error or "deepseek_empty_response"
        if attempt == retries or not deepseek_transient_error(error):
            break
        time.sleep(2 * (attempt + 1))
    safe_error = str(error).replace(api_key, "[redacted]")
    if "timeout" in safe_error.lower() or "timed out" in safe_error.lower() or "curl_exit_28" in safe_error:
        safe_error = (
            f"deepseek_timeout: 模型在 {deepseek_timeout_seconds()} 秒内未完成响应"
            f"（共尝试 {attempt + 1} 次）；文案和已有知识卡已保留。{safe_error}"
        )
    return None, truncate_error(safe_error)


def deepseek_request_once(url, payload, api_key):
    response, error = call_deepseek_with_curl(url, payload, api_key)
    # Fall back only when curl cannot run. A submitted request that timed out
    # must not be silently repeated through a different HTTP client.
    if not (error or "").startswith("curl_unavailable:"):
        return response, error
    return call_deepseek_with_urllib(url, payload, api_key)


def call_deepseek_with_urllib(url, payload, api_key):
    request = urllib.request.Request(
        url,
        data=json_dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=deepseek_timeout_seconds()) as response:
            return response.read().decode("utf-8"), None
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace").replace(api_key, "[redacted]")
        return None, truncate_error(f"deepseek_http_{exc.code}: {detail}")
    except (TimeoutError, urllib.error.URLError) as exc:
        message = str(exc).replace(api_key, "[redacted]")
        category = "deepseek_timeout" if isinstance(exc, TimeoutError) or "timed out" in message.lower() else "deepseek_network_error"
        return None, truncate_error(f"{category}: {message}")
    except Exception as exc:
        return None, f"deepseek_transport_error: {type(exc).__name__}"


def call_deepseek_with_curl(url, payload, api_key):
    request_timeout = deepseek_timeout_seconds()
    connect_timeout = min(request_timeout, deepseek_int_setting("DEEPSEEK_CONNECT_TIMEOUT_SECONDS", 15, 3, 60))
    try:
        with tempfile.TemporaryDirectory(prefix="decor-deepseek-") as directory:
            payload_file = Path(directory) / "payload.json"
            payload_file.write_text(json_dumps(payload), encoding="utf-8")
            payload_file.chmod(0o600)
            header_file = Path(directory) / "headers.conf"
            header_file.write_text("header = " + json.dumps(f"Authorization: Bearer {api_key}") + "\n", encoding="utf-8")
            header_file.chmod(0o600)
            command = [
                "curl", "--config", str(header_file), "-sS",
                "--connect-timeout", str(connect_timeout), "--max-time", str(request_timeout),
                "-w", "\n%{http_code}", url,
                "-H", "Content-Type: application/json", "--data-binary", f"@{payload_file}",
            ]
            result = subprocess.run(command, capture_output=True, text=True, timeout=request_timeout + 10, check=False)
    except subprocess.TimeoutExpired:
        return None, f"deepseek_timeout: curl_process_timeout after {request_timeout + 10}s"
    except (FileNotFoundError, PermissionError):
        return None, "curl_unavailable: cannot execute curl"
    except Exception as exc:
        return None, f"curl_execution_error: {type(exc).__name__}"
    if result.returncode != 0:
        detail = result.stderr.strip().replace(api_key, "[redacted]")
        return None, truncate_error(f"curl_exit_{result.returncode}: {detail}")
    text, _, status_text = result.stdout.rpartition("\n")
    try:
        status_code = int(status_text)
    except ValueError:
        return None, "invalid_curl_status"
    if 200 <= status_code < 300:
        return text, None
    return None, truncate_error(f"deepseek_http_{status_code}: {text.replace(api_key, '[redacted]')}")


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
    include_pinned = payload.get("include_pinned") is True
    pinned_urls = {
        canonical_video_url(item.get("source_url") or item.get("url") or "")
        for item in items if is_pinned_video(item)
    } if not include_pinned else set()
    candidates = []
    for index, item in enumerate(items):
        if not isinstance(item, dict) or (is_pinned_video(item) and not include_pinned):
            continue
        source_url = canonical_video_url(item.get("source_url") or item.get("url") or "")
        if not source_url or source_url in pinned_urls:
            continue
        candidates.append((index, item, source_url))
        if len(candidates) >= limit:
            break
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
    skipped_videos = []
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
              ad_review=CASE WHEN videos.title IS DISTINCT FROM excluded.title THEN NULL ELSE videos.ad_review END,
              platform=excluded.platform,
              creator=excluded.creator,
              published_at=COALESCE(excluded.published_at, videos.published_at),
              published_at_ts=COALESCE(excluded.published_at_ts, videos.published_at_ts),
              status=CASE
                WHEN COALESCE(videos.has_transcript, false) THEN videos.status
                ELSE videos.status
              END,
              updated_at=excluded.updated_at
            WHERE videos.deleted_at IS NULL
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
        row = conn.execute("SELECT * FROM videos WHERE source_url = %s", (source_url,)).fetchone()
        if row is None:
            raise RuntimeError("collected_video_not_found")
        if row["deleted_at"] is not None:
            skipped_videos.append({
                "id": row["id"],
                "title": row["title"],
                "source_url": source_url,
                "reason_code": "previously_deleted",
                "reason": "此前已删除，本次更新跳过，不自动恢复",
                "delete_reason": row["delete_reason"] or "",
            })
            continue
        video = row_to_video(row)
        is_duplicate = source_url in existing_urls
        video["dedupe_status"] = "duplicate" if is_duplicate else "created"
        saved.append(video)
        if is_duplicate:
            duplicate_count += 1
        else:
            created_count += 1
        existing_urls.add(source_url)

    invalidate_bootstrap_cache()
    return {
        "source_id": source_id,
        "videos": saved,
        "skipped_videos": skipped_videos,
        "stats": {
            "received": len(items[:limit]),
            "saved": len(saved),
            "created": created_count,
            "duplicate": duplicate_count,
            "skipped_deleted": len(skipped_videos),
        },
    }


def collection_skip_messages(result):
    messages = []
    for video in result.get("skipped_videos", []):
        message = f"《{video['title']}》：{video['reason']}。"
        if video.get("delete_reason"):
            message += f"原删除原因：{video['delete_reason']}"
        messages.append(message)
    return messages


def collection_update_message(result):
    stats = result["stats"]
    message = f"采集完成：新增 {stats['created']} 条，重复 {stats['duplicate']} 条。"
    if stats.get("skipped_deleted"):
        message += f"跳过已删除视频 {stats['skipped_deleted']} 条（此前已删除，不自动恢复）。"
    return "\n".join([message, *collection_skip_messages(result)])


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
        "id": account.get("id") or "tg_" + hashlib.sha256((email.lower() or token).encode()).hexdigest()[:16],
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
    # Explicit pool replaces the legacy default, so a stale default token cannot
    # register the same account twice. Credentials never enter task records.
    configured = os.environ.get("TRANSCRIPTGENERATE_ACCOUNTS", "").strip()
    payload = json.loads(configured) if configured else []
    if not isinstance(payload, list):
        raise RuntimeError("TRANSCRIPTGENERATE_ACCOUNTS must be a JSON array")
    if not payload and TRANSCRIPT_ACCOUNTS_PATH.exists():
        payload = json.loads(TRANSCRIPT_ACCOUNTS_PATH.read_text(encoding="utf-8")).get("accounts", [])
    if not payload:
        payload = [{"id": "config_default", "email": TRANSCRIPTGENERATE_EMAIL,
                    "password": TRANSCRIPTGENERATE_PASSWORD, "token": TRANSCRIPTGENERATE_TOKEN}]
    accounts, identities, ids = [], set(), set()
    for index, item in enumerate(payload, 1):
        account = normalize_transcript_account(item, index)
        if not account:
            continue
        identity = account["email"].lower() or account["token"]
        if identity in identities:
            continue
        if account["id"] in ids:
            raise RuntimeError("Duplicate transcript account id")
        accounts.append(account)
        identities.add(identity)
        ids.add(account["id"])
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


class TranscriptQuotaError(RuntimeError):
    pass


def transcript_safe_error(error, account):
    text = str(error)
    for key in ("password", "token", "runtime_token"):
        if account.get(key):
            text = text.replace(account[key], "[redacted]")
    return truncate_error(text)


def transcript_request(path, method="GET", payload=None, params=None, account=None):
    # Never choose/fail over accounts per HTTP request: task ownership is fixed.
    if account is None:
        raise RuntimeError("transcript_account_required")
    return transcript_request_with_account(account, path, method=method, payload=payload, params=params)


def transcript_request_with_account(account, path, method="GET", payload=None, params=None):
    if not account.get("runtime_token"):
        transcript_login_account(account)
    for attempt in range(2):
        try:
            response = transcript_request_once(path, method=method, payload=payload, params=params,
                                               auth=True, retry_auth=False, account=account)
        except RuntimeError as exc:
            # A create exception, even HTTP 5xx, is ambiguous. Never resend it.
            if method != "GET" or attempt or not any(
                marker in str(exc) for marker in ("transcriptgenerate_http_401", "transcriptgenerate_http_403")
            ):
                raise RuntimeError(transcript_safe_error(exc, account)) from None
            response = {"code": 401}
        if transcript_auth_expired(response):
            if attempt or not account.get("password"):
                raise RuntimeError("transcript_account_auth_failed")
            transcript_login_account(account)
            # Only an explicit authentication rejection can safely be retried.
            continue
        return response
    raise RuntimeError("transcript_account_auth_failed")


def transcript_check_quota(account):
    response = transcript_request_with_account(account, "/ai-face/userBenefitsAndUsage")
    if not isinstance(response, dict) or response.get("code") not in (200, "200"):
        raise RuntimeError("transcript_quota_check_failed")
    data = response.get("data") or {}
    benefit = next((item for item in data.get("benefits", [])
                    if item.get("functionKey") == "VIDEO_TO_TEXT"), None)
    if benefit is None:
        raise RuntimeError("transcript_quota_missing")
    remaining = benefit.get("remainingAmount")
    unlimited = float(benefit.get("totalQuota") or 0) == -1
    if not unlimited and remaining is None:
        raise RuntimeError("transcript_quota_unknown")
    if benefit.get("status") is False or benefit.get("isLimitReached") or (not unlimited and float(remaining) <= 0):
        account["status"] = "limited"
        raise TranscriptQuotaError("transcript_quota_exhausted")
    account["status"] = "available"
    return benefit


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


TRANSCRIPT_ASSIGN_LOCK_ID = 0x5447524F5441


def write_transcript_job(conn, video_id, job):
    conn.execute("UPDATE videos SET transcript_job = %s WHERE id = %s",
                 (Json(job), video_id))


def transcript_saved_result(row):
    task_id = (row.get("transcript_job") or {}).get("task_id") or "saved_transcript"
    return {"task_id": task_id, "transcript_text": row["transcript_text"],
            "raw_result": {"preserved_existing": True}}


def fetch_transcript_from_transcriptgenerate(video_url, log=None, conn=None, video_id=None):
    if conn is None or not video_id:
        raise RuntimeError("transcript_persistent_video_required")
    accounts = get_transcript_accounts()
    row = conn.execute("SELECT * FROM videos WHERE id = %s AND deleted_at IS NULL", (video_id,)).fetchone()
    if not row:
        raise RuntimeError("video not found")
    job = dict(row.get("transcript_job") or {})
    if job and job.get("provider") != "transcriptgenerate":
        if job.get("provider") == "local_asr" and job.get("state") in ("failed", "succeeded"):
            job = {}  # A terminal local attempt cannot hide an outstanding paid API task.
        else:
            raise RuntimeError("unsupported_transcript_provider")
    if job.get("state") in ("creating", "creation_uncertain") and not job.get("task_id"):
        raise RuntimeError("文案任务创建结果不明，已阻止重复提交；请先在原账号核对任务")
    if not job.get("task_id"):
        # Serializes account allocation across threads/processes, and commits the
        # intent BEFORE the only create call. The cursor survives app restarts.
        with conn.transaction():
            conn.execute("SELECT pg_advisory_xact_lock(%s)", (TRANSCRIPT_ASSIGN_LOCK_ID,))
            last = conn.execute("""SELECT transcript_job->>'account_id' AS account_id
                FROM videos WHERE transcript_job->>'assigned_at' IS NOT NULL
                ORDER BY (transcript_job->>'assigned_at')::bigint DESC LIMIT 1""").fetchone()
            enabled = [a for a in accounts if a.get("enabled", True)]
            ids = [a["id"] for a in enabled]
            start = (ids.index(last["account_id"]) + 1) % len(ids) if last and last["account_id"] in ids else 0
            ordered = enabled[start:] + enabled[:start]
            errors = []
            for account in ordered:
                try:
                    transcript_check_quota(account)
                except Exception as exc:
                    errors.append(account["id"] + ": " + transcript_safe_error(exc, account))
                    continue  # No create has happened: safe to try next account.
                job = {"provider": "transcriptgenerate", "account_id": account["id"],
                       "state": "creating", "assigned_at": time.time_ns(),
                       "input_hash": hashlib.sha256((row["transcript_text"] or "").encode()).hexdigest()}
                write_transcript_job(conn, video_id, job)
                break
            else:
                raise RuntimeError("所有文案账号不可用或额度不足：" + "；".join(errors))
        if log:
            log("已分配文案账号 " + job["account_id"])
        try:
            # No automatic retry, no account failover once submission begins.
            create_response = transcript_request_once(
                "/transcript/createTask", method="POST", retry_auth=False, account=account,
                payload={"appType": "transcript", "workUrl": video_url, "type": "text", "targetLanguage": "auto"},
            )
            if not isinstance(create_response, dict) or create_response.get("code") not in (200, "200"):
                # A documented quota rejection is definitive, but this video is
                # still blocked until the next explicit request; never hidden resend.
                if transcript_is_limit_response(create_response):
                    job.update(state="rejected", error="transcript_quota_exhausted")
                    write_transcript_job(conn, video_id, job)
                    raise TranscriptQuotaError("文案账号额度不足，本次未创建任务；可手动重试分配下一个账号")
                raise RuntimeError("transcript_create_rejected_or_unknown")
            task_id = extract_task_id(create_response)
            if not task_id:
                raise RuntimeError("transcript_task_id_missing")
            job.update(state="pending", task_id=task_id)
            write_transcript_job(conn, video_id, job)  # autocommit, before first poll
        except TranscriptQuotaError:
            raise
        except Exception as exc:
            job.update(state="creation_uncertain", error=transcript_safe_error(exc, account))
            write_transcript_job(conn, video_id, job)
            raise RuntimeError("文案任务创建结果不明，已保留账号并阻止自动重发；请在原账号核对任务") from None
    account = next((a for a in accounts if a["id"] == job["account_id"]), None)
    if account is None:
        raise RuntimeError("原文案任务账号已移除，无法续查；请恢复相同 account id 的配置")
    # Disabled/limited accounts are still allowed to query their existing tasks.
    task_id = job["task_id"]
    if log:
        log(f"使用原账号续查文案任务 {task_id}")
    for poll_index in range(TRANSCRIPT_MAX_POLLS):
        try:
            response = transcript_request_with_account(account, "/transcript/queryTask", params={"taskId": task_id})
            data = response.get("data", response) if isinstance(response, dict) else {}
            status = str(data.get("status") or "").upper() if isinstance(data, dict) else ""
            job.update(provider_status=status, last_checked_at=now())
            if status in ("FAILURE", "FAILED", "FAIL", "ERROR"):
                job.update(state="failed", error="transcript_provider_task_failed")
                write_transcript_job(conn, video_id, job)
                raise RuntimeError("文案服务任务失败，任务号已保留；请在原账号检查，不自动创建新任务")
            if response.get("code") not in (200, "200", None):
                raise RuntimeError("transcript_query_rejected")
            if status == "SUCCESS":
                text = data.get("textContent")
                if not isinstance(text, str) or not text.strip():
                    raise RuntimeError("transcript_success_without_text")
                # Save only after provider success. Titles/partial text never qualify.
                return {"task_id": task_id, "transcript_text": text.strip(), "raw_result": response,
                        "provider": "transcriptgenerate", "account_id": account["id"], "job": job}
            write_transcript_job(conn, video_id, job)
            if log:
                log(f"第 {poll_index + 1} 次检查：文案服务处理中")
        except Exception as exc:
            job["error"] = transcript_safe_error(exc, account)
            write_transcript_job(conn, video_id, job)
            raise RuntimeError(job["error"] + "；已保留任务，下次仅使用原账号续查") from None
        time.sleep(TRANSCRIPT_POLL_INTERVAL_SECONDS)
    job["error"] = "transcript_task_timeout"
    write_transcript_job(conn, video_id, job)
    raise RuntimeError("文案查询超时，任务已保存；下次只续查原任务，不重新创建")


def set_video_promotion(conn, video_id, decision):
    labels = {"not_ad": "普通内容", "uncertain": "疑似推广", "advertising": "推广"}
    if decision not in (*labels, "auto"):
        raise ValueError("请选择普通内容、疑似推广、推广或恢复自动识别")
    override = None if decision == "auto" else {
        "decision": decision, "source": "manual", "reviewed_at": now(),
        "reason": f"管理员手动标记为{labels[decision]}", "evidence": [],
    }
    row = conn.execute("""UPDATE videos SET ad_review_override=%s, updated_at=%s
        WHERE id=%s AND deleted_at IS NULL RETURNING *""",
        (Json(override) if override is not None else None, now(), video_id)).fetchone()
    invalidate_bootstrap_cache()
    return row


def review_video_advertising(conn, video_id):
    with video_process_lock(video_id):
        row = conn.execute("SELECT * FROM videos WHERE id = %s AND deleted_at IS NULL", (video_id,)).fetchone()
        if not row:
            raise ValueError("video not found")
        cached = advertising.current_review(row)
        if cached and cached.get("decision") != "error":
            return cached
        if not (row["transcript_text"] or "").strip():
            return {"decision": "pending", "reason": "等待真实文案后识别推广"}
        review = advertising.classify(row, call_deepseek, parse_deepseek_content)
        review["reviewed_at"] = now()
        updated = conn.execute("""UPDATE videos SET ad_review = %s
            WHERE id = %s AND deleted_at IS NULL
              AND transcript_text IS NOT DISTINCT FROM %s AND title = %s RETURNING id""",
            (Json(review), video_id, row["transcript_text"], row["title"])).fetchone()
        if not updated:
            return {"decision": "uncertain", "reason": "文案已变化，需要重新识别"}
        invalidate_bootstrap_cache()
        current = conn.execute("SELECT * FROM videos WHERE id = %s AND deleted_at IS NULL", (video_id,)).fetchone()
        return advertising.current_review(current) if current else {"decision": "uncertain", "reason": "视频已删除"}


def get_transcript_provider():
    with TRANSCRIPT_SETTINGS_LOCK:
        if TRANSCRIPT_SETTINGS_PATH.exists():
            value = json.loads(TRANSCRIPT_SETTINGS_PATH.read_text(encoding="utf-8"))
            provider = value.get("provider")
        else:
            provider = TRANSCRIPT_PROVIDER
    if provider not in ("local_asr", "transcriptgenerate"):
        raise RuntimeError("unsupported_transcript_provider")
    return provider


def check_local_asr_health():
    try:
        process = subprocess.run([sys.executable, str(ROOT / "local_asr.py"), "--health-check"],
                                 capture_output=True, text=True, timeout=45)
        if process.returncode:
            return {"ready": False, "status": "unavailable",
                    "message": "本地 ASR 不可用，请检查依赖、FFmpeg 和模型；运行 scripts/setup_local_asr.py 安装模型。"}
        result = json.loads(process.stdout)
        if not isinstance(result, dict) or not isinstance(result.get("ready"), bool) or result.get("status") not in ("ready", "busy"):
            raise ValueError("invalid local ASR health response")
        if result["ready"] and result["status"] != "ready":
            raise ValueError("local ASR probe did not complete")
        return {"ready": result["ready"], "status": result["status"], "message": str(result.get("message") or "本地 ASR 就绪")}
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return {"ready": False, "status": "unavailable", "message": "本地 ASR 检测失败或超时，未切换转写方式。"}


def set_transcript_provider(provider):
    if provider not in ("local_asr", "transcriptgenerate"):
        raise ValueError("不支持的转写方式")
    health = check_local_asr_health() if provider == "local_asr" else None
    if health is not None and not health["ready"]:
        return {"provider": get_transcript_provider(), "local_health": health, "saved": False}
    with TRANSCRIPT_SETTINGS_LOCK:
        # Atomic replacement keeps credentials/config untouched and survives restarts.
        fd, temp = tempfile.mkstemp(prefix=".transcription-settings-", dir=TRANSCRIPT_SETTINGS_PATH.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as output:
                json.dump({"provider": provider}, output)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temp, TRANSCRIPT_SETTINGS_PATH)
        finally:
            Path(temp).unlink(missing_ok=True)
    return {"provider": provider, "local_health": health, "saved": True}


def fetch_transcript_from_local_asr(video_url, conn, row, log=None):
    job = {"provider": "local_asr", "task_id": "local-" + uuid.uuid4().hex,
           "state": "running", "started_at": now(),
           "input_hash": hashlib.sha256((row["transcript_text"] or "").encode()).hexdigest()}
    write_transcript_job(conn, row["id"], job)
    if log:
        log("本地 ASR 排队/处理中（CPU 单任务，不调用外部文案服务）")
    try:
        process = subprocess.run([sys.executable, str(ROOT / "local_asr.py"), "--video-url", video_url],
                                 capture_output=True, text=True, timeout=10800)
        if process.returncode:
            try:
                error = json.loads(process.stderr.splitlines()[-1]).get("error", "local_asr_failed")
            except (ValueError, IndexError, AttributeError):
                error = "local_asr_failed"
            raise RuntimeError(error)
        result = json.loads(process.stdout)
        if not isinstance(result.get("transcript_text"), str) or not result["transcript_text"].strip():
            raise RuntimeError("local_asr_empty_transcript")
        job.update(model=result.get("model"), audio_seconds=result.get("audio_seconds"),
                   elapsed_seconds=result.get("elapsed_seconds"))
        result.update(task_id=job["task_id"], job=job,
                      raw_result={key: result.get(key) for key in ("provider", "model", "audio_seconds", "elapsed_seconds", "peak_rss_mb")},
                      transcript_source="LocalASR/SenseVoiceSmall-int8/task:" + job["task_id"])
        return result
    except Exception as exc:
        error = str(exc) if isinstance(exc, RuntimeError) and str(exc).startswith("local_asr_") else "local_asr_failed; safe to retry locally"
        job.update(state="failed", error=truncate_error(error))
        write_transcript_job(conn, row["id"], job)
        raise


def save_transcript_for_video(conn, row, log=None, refresh=False):
    video, result = _save_transcript_for_video(conn, row, log=log, refresh=refresh)
    video["ad_review"] = review_video_advertising(conn, video["id"])
    return video, result


def _save_transcript_for_video(conn, row, log=None, refresh=False):
    video_id = row["id"]
    # Session advisory lock covers create + poll + save; parallel endpoints cannot
    # submit twice. Its automatic release on disconnect also handles app crashes.
    conn.execute("SELECT pg_advisory_lock(hashtextextended(%s, 0))", ("transcript:" + video_id,))
    try:
        row = conn.execute("SELECT * FROM videos WHERE id = %s AND deleted_at IS NULL", (video_id,)).fetchone()
        if not row:
            raise RuntimeError("video not found")
        job = row.get("transcript_job") or {}
        if video_has_saved_transcript(row) and not refresh:
            if log:
                log("已有文案，直接保留；未重复提交转写")
            return row_to_video(row), transcript_saved_result(row)
        # A completed job can be reused even when a caller explicitly retries.
        # No paid retranscription without clearing/reconciling the prior task.
        if job.get("state") == "succeeded" and video_has_saved_transcript(row):
            return row_to_video(row), transcript_saved_result(row)
        video_url = canonical_video_url(row["share_url"] or row["source_url"])
        if not video_url:
            raise RuntimeError("video_link_missing")
        original_text = row["transcript_text"] or ""
        # Snapshot the selected route; active work keeps its original provider.
        provider = get_transcript_provider()
        if job.get("provider") == "local_asr" and job.get("state") == "running":
            provider = "local_asr"
        if provider == "local_asr" and job.get("provider") == "transcriptgenerate" and job.get("state") not in ("failed", "rejected", "succeeded"):
            raise RuntimeError("existing_external_transcript_task_requires_reconciliation; local ASR did not call the external service")
        if provider == "local_asr":
            result = fetch_transcript_from_local_asr(video_url, conn, row, log=log)
        elif provider == "transcriptgenerate":
            result = fetch_transcript_from_transcriptgenerate(video_url, log=log, conn=conn, video_id=video_id)
        else:
            raise RuntimeError("unsupported_transcript_provider")
        ts = now()
        text = result["transcript_text"]
        job = result.get("job")
        with conn.transaction():
            current = conn.execute("SELECT * FROM videos WHERE id = %s FOR UPDATE", (video_id,)).fetchone()
            if not current or current["deleted_at"] is not None:
                raise RuntimeError("video_deleted_during_transcription")
            current_text = current["transcript_text"] or ""
            expected_hash = (job or {}).get("input_hash") or hashlib.sha256(original_text.encode()).hexdigest()
            if hashlib.sha256(current_text.encode()).hexdigest() != expected_hash:
                # A manual edit wins. Mark the task consumed to prevent reruns.
                if job:
                    job.update(state="succeeded", preserved_manual=True)
                    write_transcript_job(conn, video_id, job)
                return row_to_video(current), transcript_saved_result(current)
            conn.execute("""UPDATE videos
                SET transcript_text = %s, transcript_source = %s, transcript_created_at = %s,
                    has_transcript = %s, transcript_length = %s, last_error = NULL, ad_review = NULL,
                    status = CASE WHEN EXISTS (
                        SELECT 1 FROM claims WHERE video_id = %s AND deleted_at IS NULL
                    ) THEN status ELSE 'transcript_saved' END, updated_at = %s
                WHERE id = %s""",
                (text, result.get("transcript_source") or f"TranscriptGenerate/task:{result['task_id']}", ts, *transcript_meta(text), video_id, ts, video_id))
            if job:
                job.update(state="succeeded", completed_at=ts)
                job.pop("error", None)
                write_transcript_job(conn, video_id, job)
        invalidate_bootstrap_cache()
        updated = conn.execute("SELECT * FROM videos WHERE id = %s", (video_id,)).fetchone()
        return row_to_video(updated), result
    finally:
        conn.execute("SELECT pg_advisory_unlock(hashtextextended(%s, 0))", ("transcript:" + video_id,))


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
              AND (NOT COALESCE(v.has_transcript, false) OR COALESCE(v.ad_review_override->>'decision', v.ad_review->>'decision', '') NOT IN ('advertising', 'uncertain', 'error'))
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
            result = extract_claims_for_video(conn, row_to_video(current), automatic=True)
            item["claim_count"] = len(result.get("claims") or [])
            result_status = result.get("status")
            if result_status == "completed":
                item["stage"] = "completed"
                processed.append(item)
                if log:
                    log(f"{index + 1}/{limit} 处理完成，新增观点 {item['claim_count']} 条")
            elif result_status in ("filtered", "skipped_advertising"):
                item["stage"] = result_status
                item["message"] = result.get("message") or "无有效内容"
                processed.append(item)
                if log:
                    log(f"{index + 1}/{limit} 已跳过：{item['message']}")
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
              AND (NOT COALESCE(v.has_transcript, false) OR COALESCE(v.ad_review_override->>'decision', v.ad_review->>'decision', '') NOT IN ('advertising', 'uncertain', 'error'))
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
            "UPDATE videos SET retry_count = COALESCE(retry_count, 0) + 1, last_retry_at = %s WHERE id = %s AND deleted_at IS NULL",
            (now(), video_id),
        )
        if log:
            log(f"{video_id} 拉取文案中...")
        video, transcript_result = save_transcript_for_video(conn, row, log=log, refresh=True)
        transcript_len = int(video["transcript_length"] or 0)
        if log:
            log(f"{video_id} 文案成功，长度 {transcript_len}")
        if log:
            log(f"{video_id} DeepSeek 提取观点中...")
        result = extract_claims_for_video(conn, video, automatic=True)
        if result.get("status") not in ("completed", "filtered", "skipped_advertising"):
            raise RuntimeError(result.get("message") or result.get("status") or "观点提取失败")
        if result.get("status") == "completed":
            conn.execute("UPDATE videos SET last_error = NULL, updated_at = %s WHERE id = %s", (now(), video_id))
        if log:
            if result.get("status") in ("filtered", "skipped_advertising"):
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
        item["stage"] = result.get("status") if result.get("status") in ("filtered", "skipped_advertising") else "completed"
        item["claim_count"] = len(result.get("claims") or [])
        with QUEUE_JOB_LOCK:
            QUEUE_JOB["processed"] = [item]
            QUEUE_JOB["failed"] = []
            QUEUE_JOB["remaining"] = None
        if result.get("status") in ("filtered", "skipped_advertising"):
            queue_log("单条重试结束，已跳过观点提取：" + (result.get("message") or "无有效内容"))
        else:
            queue_log(f"单条重试结束，成功 1 条，观点 {item['claim_count']} 条")
    except Exception as exc:
        item["stage"] = "failed"
        item["error"] = truncate_error(str(exc))
        try:
            with connect() as conn:
                row = conn.execute("SELECT * FROM videos WHERE id = %s AND deleted_at IS NULL", (video_id,)).fetchone()
                if row:
                    conn.execute(
                        "UPDATE videos SET last_error = %s, updated_at = %s WHERE id = %s AND deleted_at IS NULL",
                        (item["error"], now(), video_id),
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
            "source_video_is_promotional": (video.get("ad_review") or {}).get("decision") == "advertising",
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
            "source_video_url": video["source_url"],
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


def delete_video_and_claims(conn, video_id, deleted_at, delete_reason, delete_claims=True):
    with conn.transaction():
        row = conn.execute(
            "SELECT id FROM videos WHERE id = %s AND deleted_at IS NULL FOR UPDATE", (video_id,)
        ).fetchone()
        if not row:
            return False
        if delete_claims:
            conn.execute(
                """
                UPDATE claims SET deleted_at = %s, deleted_by = %s, delete_reason = %s
                WHERE video_id = %s AND deleted_at IS NULL
                """,
                (deleted_at, "admin", delete_reason, video_id),
            )
        conn.execute(
            """
            UPDATE videos SET deleted_at = %s, deleted_by = %s, delete_reason = %s, updated_at = %s
            WHERE id = %s AND deleted_at IS NULL
            """,
            (deleted_at, "admin", delete_reason, deleted_at, video_id),
        )
    return True


def replace_claims_and_status(conn, video, run_id, claims, status, message=None):
    with conn.transaction():
        current = conn.execute(
            "SELECT transcript_text, deleted_at FROM videos WHERE id = %s FOR UPDATE", (video["id"],)
        ).fetchone()
        if not current or current["deleted_at"] is not None:
            raise ValueError("video not found")
        if current["transcript_text"] != video["transcript_text"]:
            raise ValueError("transcript changed during extraction")
        inserted = insert_claims(conn, video, run_id, claims)
        conn.execute(
            "UPDATE videos SET status = %s, last_error = %s, updated_at = %s WHERE id = %s",
            (status, message, now(), video["id"]),
        )
    return inserted


def record_extraction_error(conn, video, run_id, status, error_message, preserve_status=False):
    conn.execute(
        "UPDATE extraction_runs SET status = %s, error_message = %s WHERE id = %s",
        (status, error_message, run_id),
    )
    conn.execute(
        """
        UPDATE videos SET status = CASE WHEN %s OR EXISTS (
            SELECT 1 FROM claims WHERE video_id = %s AND deleted_at IS NULL
        ) THEN status ELSE %s END, last_error = %s, updated_at = %s
        WHERE id = %s AND deleted_at IS NULL AND transcript_text = %s
        """,
        (preserve_status, video["id"], video_status_for_processing_error(video), error_message, now(), video["id"], video["transcript_text"]),
    )


def extract_claims_for_video(conn, video, automatic=False):
    with video_process_lock(video["id"]):
        if automatic:
            review = review_video_advertising(conn, video["id"])
            if review.get("decision") != "not_ad":
                return {"status": "skipped_advertising", "claims": [], "ad_review": review,
                        "message": review.get("reason") or "推广识别未通过，已跳过自动观点提取"}
        return extract_claims_for_video_locked(conn, video)


def extract_claims_for_video_locked(conn, video):
    transcript_length = len((video.get("transcript_text") or "").strip())
    if transcript_length < MIN_TRANSCRIPT_LENGTH:
        filtered_message = FILTER_REASON_MESSAGES["duplicate_or_too_thin"]
        detail_message = f"{filtered_message}，当前长度 {transcript_length}"
        replace_claims_and_status(conn, video, None, [], "claims_filtered", detail_message)
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
    status = "completed" if raw_response else (error or "empty_response")
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
    if status != "completed":
        error_message = truncate_error(status)
        record_extraction_error(conn, video, run_id, status, error_message)
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
        if not isinstance(extracted, dict) or not isinstance(extracted.get("claims"), list):
            raise ValueError("deepseek_invalid_claims_shape")
        sanitized_claims, dropped_claims = sanitize_claims(
            extracted["claims"], transcript_text=video["transcript_text"], require_evidence=True
        )
        if sanitized_claims:
            claims = replace_claims_and_status(conn, video, run_id, sanitized_claims, "claims_extracted")
            return {"run_id": run_id, "status": "completed", "claims": claims, "dropped_claims": dropped_claims}

        if extracted["claims"] or extracted.get("filter_reason") not in FILTER_REASON_MESSAGES:
            raise ValueError("quality_check_failed" if extracted["claims"] else "deepseek_untrusted_empty_claims")
        filtered_message = build_filtered_message(extracted, dropped_claims)
        replace_claims_and_status(conn, video, run_id, [], "claims_filtered", filtered_message)
        return {
            "run_id": run_id,
            "status": "filtered",
            "claims": [],
            "dropped_claims": dropped_claims,
            "message": filtered_message,
        }
    except ValueError as exc:
        failure_status = "quality_check_failed" if str(exc) == "quality_check_failed" else "parse_failed"
        record_extraction_error(conn, video, run_id, failure_status, truncate_error(str(exc)),
                                preserve_status=failure_status == "quality_check_failed")
        raise
    except Exception as exc:
        record_extraction_error(conn, video, run_id, "insert_failed", truncate_error(str(exc)))
        raise


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


def fetch_sources(conn):
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
        LEFT JOIN source_video_counts svc ON svc.source_id = s.id
        LEFT JOIN source_claim_counts scc ON scc.source_id = s.id
        ORDER BY
          CASE s.priority WHEN 'P0' THEN 0 WHEN 'P1' THEN 1 ELSE 2 END,
          s.created_at DESC, s.id
        """
    ).fetchall()
    return [row_to_source(row) for row in rows]


def fetch_video_facets(conn):
    # Use all active videos, including those without a source; page filters never apply here.
    rows = conn.execute(
        """
        SELECT platform, creator, COUNT(*) AS video_count
        FROM videos
        WHERE deleted_at IS NULL
        GROUP BY platform, creator
        ORDER BY platform, creator
        """
    ).fetchall()
    platform_counts = {}
    creators = []
    total = 0
    for row in rows:
        platform = row["platform"] or ""
        creator = row["creator"] or ""
        count = int(row["video_count"])
        total += count
        if platform.strip():
            platform_counts[platform] = platform_counts.get(platform, 0) + count
        if creator.strip():
            creators.append({"platform": platform, "creator": creator, "video_count": count})
    return {
        "platforms": [
            {"platform": platform, "video_count": count}
            for platform, count in platform_counts.items()
        ],
        "creators": creators,
        "total": total,
    }


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
            v.transcript_source, v.transcript_created_at, v.ad_review, v.ad_review_override, v.transcript_text,
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
          v.transcript_source, v.transcript_created_at, v.ad_review, v.ad_review_override, v.transcript_text,
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
        "facets": fetch_video_facets(conn),
    }


def progress_state_sql():
    return """
      CASE
        WHEN COALESCE(v.ad_review_override->>'decision', v.ad_review->>'decision') = 'advertising' THEN '已完成'
        WHEN COALESCE(v.ad_review_override->>'decision', v.ad_review->>'decision') IN ('uncertain', 'error') THEN '待确认'
        WHEN v.status = 'claims_filtered' THEN '已完成'
        WHEN v.status = 'transcript_failed' OR COALESCE(v.last_error, '') != '' THEN '失败'
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
            v.transcript_source, v.transcript_created_at, v.ad_review, v.ad_review_override, v.transcript_text,
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



def fetch_knowledge_facets(conn):
    # Facets always describe the whole active library, independent of page/search filters.
    tags = sorted(set(TAGS["space_tags"] + TAGS["topic_tags"]))
    rows = conn.execute(
        """
        WITH active_claims AS MATERIALIZED (
          SELECT id, process_stage, stance, space_tags, topic_tags
          FROM claims
          WHERE deleted_at IS NULL
        )
        SELECT 'total' AS facet, '' AS value, COUNT(*) AS count FROM active_claims
        UNION ALL
        SELECT 'stages', process_stage, COUNT(*) FROM active_claims GROUP BY process_stage
        UNION ALL
        SELECT 'stances', stance, COUNT(*) FROM active_claims GROUP BY stance
        UNION ALL
        SELECT 'tags', candidate.tag, COUNT(c.id)
        FROM unnest(%s::text[]) AS candidate(tag)
        LEFT JOIN active_claims c ON (
          c.space_tags ? candidate.tag OR c.topic_tags ? candidate.tag
          OR c.process_stage LIKE ('%%' || candidate.tag || '%%')
        )
        GROUP BY candidate.tag
        """,
        (tags,),
    ).fetchall()
    facets = {"total": 0, "stages": {}, "stances": {}, "tags": {}}
    for row in rows:
        count = int(row["count"])
        if row["facet"] == "total":
            facets["total"] = count
        else:
            facets[row["facet"]][row["value"]] = count
    return facets


def fetch_knowledge_page(conn, query=None, limit=DEFAULT_KNOWLEDGE_LIMIT, offset=0):
    query = query or {}
    clauses = ["deleted_at IS NULL"]
    params = []
    stage = (query.get("stage") or [""])[0]
    stages = [item.strip() for item in (query.get("stages") or [""])[0].split(",") if item.strip()]
    tag = (query.get("tag") or [""])[0]
    stance = (query.get("stance") or [""])[0]
    q = (query.get("q") or [""])[0]
    if stages:
        clauses.append("process_stage = ANY(%s)")
        params.append(stages)
    elif stage:
        clauses.append("process_stage = %s")
        params.append(stage)
    if tag:
        # Keep legacy tag=<stance> clients working alongside the explicit stance parameter.
        clauses.append("(space_tags ? %s OR topic_tags ? %s OR process_stage LIKE %s OR stance = %s)")
        params.extend([tag, tag, f"%{tag}%", tag])
    if stance:
        clauses.append("stance = %s")
        params.append(stance)
    if q:
        clauses.append(
            "(COALESCE(object_name, '') || ' ' || COALESCE(original_conclusion, '') || ' ' || COALESCE(conditions, '') || ' ' || COALESCE(original_reasons::text, '') ILIKE %s)"
        )
        params.append(f"%{q}%")
    where = f"WHERE {' AND '.join(clauses)}"
    total = conn.execute(f"SELECT COUNT(*) AS count FROM claims {where}", params).fetchone()["count"]
    rows = conn.execute(
        f"SELECT * FROM claims {where} ORDER BY created_at DESC, id DESC LIMIT %s OFFSET %s",
        [*params, limit, offset],
    ).fetchall()
    return {
        "claims": claims_with_source_labels(conn, rows),
        "total": int(total or 0),
        "limit": limit,
        "offset": offset,
        "has_more": offset + len(rows) < int(total or 0),
        "facets": fetch_knowledge_facets(conn),
    }


def build_bootstrap_payload(conn):
    video_page = fetch_video_page(conn, limit=DEFAULT_VIDEO_LIMIT, offset=0)
    sources = fetch_sources(conn)

    stats_row = conn.execute(
        """
        SELECT
          COUNT(*) AS video_count,
          COUNT(*) FILTER (WHERE COALESCE(has_transcript, false)) AS transcript_count
        FROM videos
        WHERE deleted_at IS NULL
        """
    ).fetchone()
    knowledge_facets = fetch_knowledge_facets(conn)

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
        "video_facets": video_page["facets"],
        "videos_page": {
            "total": video_page["total"],
            "limit": video_page["limit"],
            "offset": video_page["offset"],
            "has_more": video_page["has_more"],
        },
        "knowledge": {"claims": [], "deferred": True, "facets": knowledge_facets},
        "stats": {
            "source_count": len(sources),
            "video_count": int(stats_row["video_count"] or 0),
            "transcript_count": int(stats_row["transcript_count"] or 0),
            "claim_count": knowledge_facets["total"],
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
        # UI and API share an origin; do not grant arbitrary sites credentialed access.
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
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
        if PUBLIC_READ_ONLY:
            public_paths = {"/api/health", "/api/admin/session", "/api/bootstrap", "/api/sources",
                            "/api/videos", "/api/knowledge", "/api/progress-summary", "/api/progress-videos"}
            video_detail = len(path.split("/")) == 4 and path.startswith("/api/videos/")
            if path not in public_paths and not video_detail:
                return self.send_error_json(403, "public instance is read-only")
            if video_detail and query.get("include_runs"):
                return self.send_error_json(403, "extraction history is private")
        if path == "/api/health":
            available, message = database_readiness()
            return self.send_json(
                {
                    "ok": available,
                    "db": "postgresql",
                    "db_available": available,
                    "db_message": message,
                    "model": DEEPSEEK_MODEL,
                },
                status=200 if available else 503,
            )

        if path == "/api/settings/transcription":
            return self.send_json({"provider": get_transcript_provider()})

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
                        "message": "已检测到抖音登录凭据；单条作品仍可能因权限或删除无法访问。" if status.get("logged_in") else "未检测到抖音登录凭据，请重新登录。",
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
                return self.send_json({"sources": fetch_sources(conn)})

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
                    "claims": [row_to_claim(item, source_video=row) for item in claims],
                }
                if (query.get("include_runs") or [""])[0] == "1":
                    runs = conn.execute(
                        "SELECT * FROM extraction_runs WHERE video_id = %s ORDER BY created_at DESC",
                        (video_id,),
                    ).fetchall()
                    response["extraction_runs"] = [dict(item) for item in runs]
                return self.send_json(response)

            if path == "/api/knowledge":
                limit = query_int(query, "limit", DEFAULT_KNOWLEDGE_LIMIT, minimum=1, maximum=MAX_PAGE_LIMIT)
                offset = query_int(query, "offset", 0, minimum=0)
                return self.send_json(fetch_knowledge_page(conn, query=query, limit=limit, offset=offset))

            if path == "/api/queue/next":
                transcript_row = conn.execute(
                    """
                    SELECT v.*, COUNT(c.id) AS claim_count
                    FROM videos v
                    LEFT JOIN claims c ON c.video_id = v.id AND c.deleted_at IS NULL
                    WHERE v.status = 'transcript_saved' AND v.deleted_at IS NULL
                      AND (NOT COALESCE(v.has_transcript, false) OR COALESCE(v.ad_review_override->>'decision', v.ad_review->>'decision', '') NOT IN ('advertising', 'uncertain', 'error'))
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
        if PUBLIC_READ_ONLY:
            return self.send_error_json(403, "public instance is read-only")
        if is_admin_operation_path(path) and not require_admin(self):
            return
        payload = read_json(self)
        if path == "/api/settings/transcription/check-local":
            health = check_local_asr_health()
            return self.send_json(health, status=200 if health["ready"] else 503)

        if path == "/api/settings/transcription":
            result = set_transcript_provider(payload.get("provider"))
            return self.send_json(result, status=200 if result["saved"] else 503)

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
            if path.startswith("/api/videos/") and path.endswith("/promotion"):
                video_id = path.split("/")[3]
                try:
                    row = set_video_promotion(conn, video_id, payload.get("decision"))
                except ValueError as exc:
                    return self.send_error_json(400, str(exc))
                if not row:
                    return self.send_error_json(404, "video not found")
                return self.send_json({"video": row_to_video(row)})

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
                      ad_review=CASE WHEN videos.title IS DISTINCT FROM excluded.title THEN NULL ELSE videos.ad_review END,
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
                video = row_to_video(row)
                if row["has_transcript"]:
                    video["ad_review"] = review_video_advertising(conn, row["id"])
                return self.send_json({"video": video}, status=201)

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
                text = (payload.get("transcript_text") or "").strip()
                source = (payload.get("transcript_source") or "").strip() or "manual"
                existing = conn.execute("SELECT * FROM videos WHERE source_url = %s", (share_url,)).fetchone()
                ts = now()
                video_id = existing["id"] if existing else payload.get("id") or new_id("vid")
                published_at = payload.get("published_at") or (existing["published_at"] if existing else None)
                # Persist the video first: a failed/uncertain create still has a
                # durable task record. Duplicate imports keep existing transcripts.
                conn.execute("""INSERT INTO videos (
                    id, source_id, platform, creator, title, source_url, share_url, share_text,
                    published_at, published_at_ts, transcript_text, transcript_source,
                    transcript_created_at, has_transcript, transcript_length, status, created_at, updated_at
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT(source_url) DO UPDATE SET
                    title=excluded.title,
                    ad_review=CASE WHEN videos.title IS DISTINCT FROM excluded.title THEN NULL ELSE videos.ad_review END,
                    platform=excluded.platform, creator=excluded.creator,
                    share_url=excluded.share_url, share_text=excluded.share_text,
                    published_at=COALESCE(excluded.published_at, videos.published_at),
                    published_at_ts=COALESCE(excluded.published_at_ts, videos.published_at_ts),
                    deleted_at=NULL, deleted_by=NULL, delete_reason=NULL, updated_at=excluded.updated_at""",
                    (video_id, payload.get("source_id") or (existing["source_id"] if existing else None),
                     payload.get("platform") or (existing["platform"] if existing else None) or infer_platform(share_url),
                     payload.get("creator") or (existing["creator"] if existing else None) or "待识别",
                     payload.get("title") or (existing["title"] if existing else None) or infer_title(share_text, text),
                     share_url, share_url, share_text, published_at, parse_published_at(published_at),
                     text or None, source if text else None, ts if text else None, *transcript_meta(text),
                     "transcript_saved" if text else "transcript_pending", ts, ts))
                row = conn.execute("SELECT * FROM videos WHERE source_url = %s", (share_url,)).fetchone()
                video_id = row["id"]  # A simultaneous import may have won the URL.
                if text:
                    conn.execute("""UPDATE videos SET transcript_text=%s, transcript_source=%s,
                        transcript_created_at=%s, has_transcript=true, transcript_length=%s,
                        status='transcript_saved', last_error=NULL, ad_review=NULL, updated_at=%s WHERE id=%s""",
                        (text, source, ts, len(text), ts, video_id))
                    row = conn.execute("SELECT * FROM videos WHERE id=%s", (video_id,)).fetchone()
                    video = row_to_video(row)
                    video["ad_review"] = review_video_advertising(conn, video_id)
                    transcript_result = {"task_id": "provided_transcript", "transcript_text": text,
                                         "raw_result": {"source": source}}
                else:
                    try:
                        video, transcript_result = save_transcript_for_video(conn, row)
                    except RuntimeError as exc:
                        invalidate_bootstrap_cache()
                        return self.send_error_json(502, truncate_error(str(exc)))
                response = {"video": video, "transcript": {
                    "task_id": transcript_result["task_id"],
                    "transcript_text": transcript_result["transcript_text"],
                    "raw_result": transcript_result.get("raw_result", {}),
                }}
                if payload.get("extract"):
                    response["extraction"] = extract_claims_for_video(conn, video, automatic=True)
                    refreshed = conn.execute("SELECT * FROM videos WHERE id = %s", (video_id,)).fetchone()
                    response["video"] = row_to_video(refreshed)
                invalidate_bootstrap_cache()
                return self.send_json(response, status=201)

            if path.startswith("/api/videos/") and path.endswith("/transcript"):
                video_id = path.split("/")[3]
                transcript_text = payload.get("transcript_text")
                if not isinstance(transcript_text, str) or not transcript_text.strip():
                    return self.send_error_json(400, "transcript_text must be a non-empty string")
                ts = now()
                updated = conn.execute(
                    """
                    UPDATE videos
                    SET transcript_text = %s, transcript_source = %s, transcript_created_at = %s,
                        has_transcript = %s, transcript_length = %s,
                        status = 'transcript_saved', last_error = NULL, ad_review = NULL, updated_at = %s
                    WHERE id = %s AND deleted_at IS NULL
                    RETURNING *
                    """,
                    (
                        transcript_text,
                        payload.get("transcript_source", "manual"),
                        ts,
                        *transcript_meta(transcript_text),
                        ts,
                        video_id,
                    ),
                ).fetchone()
                if not updated:
                    return self.send_error_json(404, "video not found")
                invalidate_bootstrap_cache()
                video = row_to_video(updated)
                video["ad_review"] = review_video_advertising(conn, video_id)
                return self.send_json({"video": video})

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
                return self.send_json({"status": "restored", "claim": claims_with_source_labels(conn, [restored])[0]})

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
                      AND (NOT COALESCE(v.has_transcript, false) OR COALESCE(v.ad_review_override->>'decision', v.ad_review->>'decision', '') NOT IN ('advertising', 'uncertain', 'error'))
                    GROUP BY v.id
                    HAVING COUNT(c.id) = 0
                    ORDER BY v.published_at_ts DESC NULLS LAST, v.created_at DESC
                    LIMIT 1
                    """
                ).fetchone()
                if not row:
                    return self.send_json({"status": "empty", "message": "no transcript_saved videos waiting for extraction"})
                video = row_to_video(row)
                result = extract_claims_for_video(conn, video, automatic=True)
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
                result["message"] = collection_update_message(result)
                return self.send_json(result, status=201)

            if path == "/api/sources/update-all":
                try:
                    limit = int(payload.get("limit", 5))
                except (TypeError, ValueError):
                    return self.send_error_json(400, "limit must be a positive integer")
                if limit < 1:
                    return self.send_error_json(400, "limit must be positive")
                rows = conn.execute(
                    "SELECT * FROM sources WHERE status = 'active' ORDER BY priority, created_at DESC, id"
                ).fetchall()
                results = []
                stats = {"received": 0, "saved": 0, "created": 0, "duplicate": 0, "skipped_deleted": 0}
                summary = {"total": len(rows), "completed": 0, "failed": 0, "skipped": 0}
                for row in rows:
                    result = {
                        "source_id": row["id"],
                        "name": row["name"],
                        "platform": row["platform"],
                        "stats": {"received": 0, "saved": 0, "created": 0, "duplicate": 0, "skipped_deleted": 0},
                    }
                    platform = row["platform"] or ""
                    if "douyin" not in platform.lower() and "抖音" not in platform:
                        result.update({"status": "skipped", "message": f"暂不支持 {platform} 平台采集，目前仅支持抖音。"})
                    else:
                        try:
                            if not (row["profile_url"] or "").strip():
                                raise ValueError("来源缺少主页链接")
                            collected = collect_douyin_profile(row["profile_url"], limit, creator=row["name"])
                            if not isinstance(collected, list) or not collected:
                                raise RuntimeError("douyin_collector_empty")
                            result["stats"]["received"] = len(collected[:limit])
                            with conn.transaction():
                                saved = save_collected_videos(
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
                                if not saved["stats"]["saved"] and not saved["stats"].get("skipped_deleted"):
                                    raise RuntimeError("collector_no_valid_videos")
                            result.update(saved)
                            result.update({"status": "completed", "message": collection_update_message(saved)})
                            invalidate_bootstrap_cache()
                        except Exception as exc:
                            error = truncate_error(str(exc))
                            result.update({"status": "failed", "error": error, "message": f"更新失败：{error}"})
                    results.append(result)
                    summary[result["status"]] += 1
                    for key in stats:
                        stats[key] += result["stats"].get(key, 0)

                if summary["completed"]:
                    status = "completed" if summary["completed"] == summary["total"] else "partial"
                elif summary["failed"]:
                    status = "failed"
                else:
                    status = "skipped"
                label = {"completed": "更新完成", "partial": "部分更新完成", "failed": "更新失败", "skipped": "未执行更新"}[status]
                message = (
                    f"{label}：成功 {summary['completed']} 个来源，失败 {summary['failed']} 个，跳过 {summary['skipped']} 个；"
                    f"新增 {stats['created']} 条，重复 {stats['duplicate']} 条。"
                ) if rows else "没有启用的来源，未执行更新。"
                if stats["skipped_deleted"]:
                    message += f"跳过已删除视频 {stats['skipped_deleted']} 条（此前已删除，不自动恢复）。"
                    for source in results:
                        for detail in collection_skip_messages(source):
                            message += f"\n{source['name']}：{detail}"
                return self.send_json(
                    {"status": status, "limit": limit, "sources": results, "stats": stats, "summary": summary, "message": message}
                )

        return self.send_error_json(404, "not found")

    def handle_delete(self, parsed):
        path = parsed.path
        if PUBLIC_READ_ONLY:
            return self.send_error_json(403, "public instance is read-only")
        if not DB_STATUS["available"]:
            return self.send_error_json(503, f"database unavailable: {truncate_error(DB_STATUS['message'])}")
        if not require_admin(self):
            return
        deleted_at = now()
        query = parse_qs(parsed.query, keep_blank_values=True)
        delete_reason = (query.get("reason") or [""])[0].strip()
        delete_claims = True
        if path.startswith("/api/videos/"):
            values = query.get("delete_claims", ["true"])
            if len(values) != 1 or values[0] not in ("true", "false"):
                return self.send_error_json(400, "delete_claims must be true or false")
            delete_claims = values[0] == "true"
        with connect() as conn:
            if path.startswith("/api/videos/"):
                video_id = path.split("/")[3]
                if not delete_video_and_claims(conn, video_id, deleted_at, delete_reason, delete_claims=delete_claims):
                    return self.send_error_json(404, "video not found")
                invalidate_bootstrap_cache()
                return self.send_json({"status": "deleted", "video_id": video_id, "claims_deleted": delete_claims})

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
    host = os.environ.get("HOST", "127.0.0.1")
    server = ThreadingHTTPServer((host, port), AppHandler)
    print(f"Serving API on http://{host}:{port}")
    if STATIC_ROOT:
        print(f"Serving static files from {STATIC_ROOT}")
    server.serve_forever()


if __name__ == "__main__":
    main()
