#!/usr/bin/env python3
import argparse
import datetime as dt
import json
import os
import re
import sys
import time
from urllib.parse import parse_qs, unquote, urlparse
from pathlib import Path


VALID_LOGIN_COOKIE_NAMES = {
    "sessionid",
    "sessionid_ss",
    "sid_guard",
    "sid_tt",
    "uid_tt",
    "uid_tt_ss",
}


def canonical_video_url(url):
    match = re.search(r"douyin\.com/video/(\d+)", url or "")
    return f"https://www.douyin.com/video/{match.group(1)}" if match else ""


def canonical_video_url_from_id(value):
    video_id = re.sub(r"\D", "", str(value or ""))
    return f"https://www.douyin.com/video/{video_id}" if len(video_id) >= 15 else ""


def cookie_status(context):
    cookies = context.cookies("https://www.douyin.com")
    names = sorted({cookie.get("name", "") for cookie in cookies if cookie.get("name")})
    valid_names = [name for name in names if name in VALID_LOGIN_COOKIE_NAMES]
    return {
        "logged_in": bool(valid_names),
        "cookie_count": len(cookies),
        "cookie_names": names,
        "valid_cookie_names": valid_names,
    }


def launch_context(playwright, user_data_dir, headless=False):
    executable_path = os.environ.get("CHROME_PATH", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
    launch_options = {
        "headless": headless,
        "viewport": {"width": 1440, "height": 1200},
        "locale": "zh-CN",
    }
    if Path(executable_path).exists():
        launch_options["executable_path"] = executable_path
    return playwright.chromium.launch_persistent_context(user_data_dir, **launch_options)


def safe_text(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def looks_like_aweme(value):
    if not isinstance(value, dict):
        return False
    video_id = value.get("aweme_id") or value.get("awemeId") or value.get("aweme_id_str") or value.get("item_id") or value.get("itemId")
    if not canonical_video_url_from_id(video_id):
        return False
    return any(key in value for key in ("desc", "create_time", "author", "video", "statistics", "share_info"))


def is_pinned_video(value):
    return isinstance(value, dict) and any(
        str(value.get(key, "")).strip().lower() in {"1", "true", "yes"}
        for key in ("is_top", "isTop", "is_pinned", "isPinned")
    )


def recursive_find_video_objects(value, inherited_pinned=False):
    found = []
    if isinstance(value, list):
        for item in value:
            found.extend(recursive_find_video_objects(item, inherited_pinned))
        return found
    if not isinstance(value, dict):
        return found
    pinned = inherited_pinned or is_pinned_video(value)

    video_id = (
        value.get("aweme_id")
        or value.get("awemeId")
        or value.get("aweme_id_str")
        or value.get("item_id")
        or value.get("itemId")
        or value.get("id")
    )
    source_url = canonical_video_url_from_id(video_id)
    if source_url and looks_like_aweme(value):
        share_info = value.get("share_info") if isinstance(value.get("share_info"), dict) else {}
        title = value.get("desc") or value.get("description") or value.get("title") or share_info.get("share_title") or ""
        create_time = value.get("create_time") or value.get("createTime") or value.get("create_timestamp")
        published_at = ""
        if isinstance(create_time, (int, float)) and create_time > 0:
            try:
                published_at = dt.datetime.fromtimestamp(create_time).strftime("%Y-%m-%d %H:%M:%S")
            except Exception:
                published_at = ""
        found.append(
            {
                "source_url": source_url,
                "share_url": source_url,
                "title": safe_text(title),
                "published_at": published_at,
                "is_pinned": pinned,
            }
        )

    for nested in value.values():
        if isinstance(nested, (dict, list)):
            found.extend(recursive_find_video_objects(nested, pinned))
    return found


def append_unique_videos(target, items, seen, limit, excluded=None):
    excluded = excluded if excluded is not None else set()
    # Pin evidence wins over an unmarked copy from another response or render data.
    excluded.update(item.get("source_url") for item in items if is_pinned_video(item))
    target[:] = [item for item in target if item.get("source_url") not in excluded]
    for item in items:
        source_url = item.get("source_url")
        if not source_url or source_url in seen or source_url in excluded:
            continue
        if len(target) >= limit:
            break
        seen.add(source_url)
        target.append(item)
    return len(target) >= limit


def sort_latest_videos(videos):
    return sorted(videos, key=lambda item: item.get("published_at") or "", reverse=True)


def collect_render_data_videos(page, limit, excluded=None):
    payloads = page.eval_on_selector_all(
        "script",
        """els => els.map((el) => ({
            id: el.id || '',
            text: el.textContent || ''
        })).filter((item) => item.text.includes('aweme') || item.id === 'RENDER_DATA')""",
    )
    videos = []
    seen = set()
    excluded = excluded if excluded is not None else set()
    for payload in payloads:
        text = payload.get("text") or ""
        candidates = [text]
        if payload.get("id") == "RENDER_DATA":
            candidates.insert(0, unquote(text))
        for candidate in candidates:
            try:
                data = json.loads(candidate)
            except Exception:
                continue
            append_unique_videos(videos, recursive_find_video_objects(data), seen, limit, excluded)
    return videos


def expected_sec_user_id(profile_url):
    match = re.search(r"douyin\.com/user/([^/?#]+)", profile_url or "")
    return match.group(1) if match else ""


def is_douyin_aweme_response(url, expected_sec_uid=""):
    parsed = urlparse(url)
    if "douyin.com" not in parsed.netloc:
        return False
    if not parsed.path.endswith("/aweme/v1/web/aweme/post/"):
        return False
    if expected_sec_uid:
        sec_uid = (parse_qs(parsed.query).get("sec_user_id") or [""])[0]
        return sec_uid == expected_sec_uid
    return True


def page_matches_creator(page, expected_creator):
    if not expected_creator:
        return True
    try:
        title = page.title()
    except Exception:
        title = ""
    try:
        body = page.locator("body").inner_text(timeout=5000)
    except Exception:
        body = ""
    return expected_creator in title or expected_creator in body


def main():
    parser = argparse.ArgumentParser(description="Collect recent Douyin video links from a creator profile.")
    parser.add_argument("--mode", choices=["collect", "login", "status"], default="collect")
    parser.add_argument("--profile-url", default="https://www.douyin.com/")
    parser.add_argument("--creator", default="")
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--wait-seconds", type=int, default=180)
    parser.add_argument("--user-data-dir", default=str(Path(__file__).resolve().parent / ".browser-profile" / "douyin"))
    args = parser.parse_args()

    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": "playwright_missing",
                    "message": f"缺少 Playwright 依赖，无法启动本地采集器：{exc}",
                },
                ensure_ascii=False,
            )
        )
        return 2

    with sync_playwright() as p:
        context = launch_context(p, args.user_data_dir, headless=args.mode == "status")
        if args.mode == "status":
            status = cookie_status(context)
            context.close()
            print(json.dumps({"ok": True, **status}, ensure_ascii=False))
            return 0

        candidate_limit = max(args.limit, args.limit * 5)
        profile_sec_uid = expected_sec_user_id(args.profile_url)
        response_videos = []
        response_seen = set()
        pinned_urls = set()
        response_urls = []

        def handle_response(response):
            if args.mode != "collect":
                return
            url = response.url
            if not is_douyin_aweme_response(url, profile_sec_uid):
                return
            try:
                headers = response.headers
                content_type = headers.get("content-type", "")
                if "json" not in content_type and "javascript" not in content_type and "text" not in content_type:
                    return
                data = response.json()
            except Exception:
                return
            items = recursive_find_video_objects(data)
            if not items:
                return
            response_urls.append(url)
            append_unique_videos(response_videos, items, response_seen, candidate_limit, pinned_urls)

        page = context.new_page()
        page.on("response", handle_response)
        page.goto(args.profile_url, wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(3000)

        if args.mode == "login":
            deadline = time.time() + max(10, args.wait_seconds)
            status = cookie_status(context)
            while not status["logged_in"] and time.time() < deadline:
                page.wait_for_timeout(3000)
                status = cookie_status(context)
            context.close()
            if status["logged_in"]:
                print(json.dumps({"ok": True, "message": "抖音登录态已保存。", **status}, ensure_ascii=False))
                return 0
            print(
                json.dumps(
                    {
                        "ok": False,
                        "error": "douyin_login_timeout",
                        "message": "未检测到有效抖音登录 cookie，请完成登录后重试。",
                        **status,
                    },
                    ensure_ascii=False,
                )
            )
            return 1

        for _ in range(8):
            if len(response_videos) >= candidate_limit:
                break
            page.mouse.wheel(0, 1200)
            page.wait_for_timeout(1200)
        creator_matched = page_matches_creator(page, args.creator)
        videos = response_videos[:]
        if len(videos) < candidate_limit:
            seen = {item["source_url"] for item in videos}
            render_videos = collect_render_data_videos(page, candidate_limit, pinned_urls)
            append_unique_videos(videos, render_videos, seen, candidate_limit, pinned_urls)
        login_text = page.locator("text=登录").count()
        body_text = safe_text(page.locator("body").inner_text(timeout=5000))
        status = cookie_status(context)
        context.close()

    if videos and not creator_matched:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": "douyin_creator_context_mismatch",
                    "message": "页面没有确认匹配目标博主，已拒绝保存候选视频，避免误抓热门推荐。",
                    "logged_in": status["logged_in"],
                    "candidate_count": len(videos),
                },
                ensure_ascii=False,
            )
        )
        return 1

    if not videos:
        if pinned_urls:
            print(json.dumps({
                "ok": False,
                "error": "douyin_no_unpinned_videos",
                "message": f"已跳过 {len(pinned_urls)} 条置顶视频，暂未找到可采集的非置顶作品。",
                "skipped_pinned": len(pinned_urls),
            }, ensure_ascii=False))
            return 1
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": "douyin_profile_data_unavailable",
                    "message": "没有从主页采集到可确认属于该博主的作品，可能需要重新登录抖音或刷新主页作品数据。",
                    "login_hint": login_text > 0 or not status["logged_in"],
                    "service_error_hint": "服务异常" in body_text,
                    "logged_in": status["logged_in"],
                    "creator_matched": creator_matched,
                    "candidate_count": len(response_videos),
                    "response_url_count": len(response_urls),
                },
                ensure_ascii=False,
            )
        )
        return 1

    print(json.dumps({"ok": True, "videos": sort_latest_videos(videos)[: args.limit],
                      "skipped_pinned": len(pinned_urls)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
