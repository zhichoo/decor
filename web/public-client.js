/* Read-only, local snapshot queries. No API server or write transport exists. */
(() => {
  "use strict";
  const script = document.currentScript;
  const snapshot = script.dataset.snapshot;
  const snapshotURL = new URL(snapshot, script.src);
  if (snapshotURL.origin !== window.location.origin) throw new Error("Snapshot must be same-origin");
  let pending;

  function load() {
    if (!pending) {
      pending = fetch(snapshotURL, { credentials: "omit", cache: "no-cache" })
        .then((response) => {
          if (!response.ok) throw new Error("公开快照暂时无法加载，请刷新重试。");
          return response.json();
        })
        .then((data) => {
          if (data.format_version !== 1 || !Array.isArray(data.videos) || !Array.isArray(data.claims)) {
            throw new Error("公开快照格式不兼容。");
          }
          return data;
        })
        .catch((error) => { pending = null; throw error; });
    }
    return pending;
  }

  const contains = (text, query) => String(text || "").toLocaleLowerCase().includes(query.toLocaleLowerCase());
  function page(items, params, key, fallback) {
    const integer = (name, defaultValue) => /^\d+$/.test(params.get(name) || "") ? Number(params.get(name)) : defaultValue;
    const limit = Math.max(1, Math.min(100, integer("limit", fallback)));
    const offset = integer("offset", 0);
    return { [key]: items.slice(offset, offset + limit), total: items.length, limit, offset,
      has_more: offset + limit < items.length };
  }

  function summary(video) {
    const { transcript_text, ...result } = video;
    return result;
  }

  async function get(path) {
    const url = new URL(path.startsWith("/") && !path.startsWith("/api/") ? `/api${path}` : path, window.location.origin);
    if (url.origin !== window.location.origin) throw new Error("公开预览不连接外部管理接口。");
    if (url.pathname === "/api/admin/session") return { authenticated: false, configured: false, read_only: true };
    const data = await load();
    const params = url.searchParams;
    let result;
    switch (url.pathname) {
      case "/api/health":
        result = { ok: true, db_available: true, mode: "static", published_at: data.published_at };
        break;
      case "/api/bootstrap": {
        const first = page(data.videos.map(summary), new URLSearchParams(), "videos", 30);
        result = { health: { ok: true, db_available: true, mode: "static" }, sources: data.sources,
          videos: first.videos, videos_page: first, video_facets: data.video_facets,
          knowledge: { claims: [], deferred: true, facets: data.knowledge_facets }, stats: data.stats };
        break;
      }
      case "/api/sources":
        result = { sources: data.sources };
        break;
      case "/api/videos": {
        const items = data.videos.filter((video) => ["source_id", "platform", "creator"].every((field) => {
          const value = params.get(field);
          return !value || value === "全部" || video[field] === value;
        }) && (!params.get("q") || contains(`${video.title} ${video.creator} ${video.platform}`, params.get("q"))));
        result = { ...page(items.map(summary), params, "videos", 30), facets: data.video_facets };
        break;
      }
      case "/api/knowledge": {
        const stages = (params.get("stages") || "").split(",").filter(Boolean);
        const stage = params.get("stage");
        const tag = params.get("tag");
        const stance = params.get("stance");
        const authorStance = params.get("author_stance");
        const contentType = params.get("content_type");
        const query = params.get("q");
        const items = data.claims.filter((claim) =>
          (!stages.length ? !stage || claim.process_stage === stage : stages.includes(claim.process_stage)) &&
          (!tag || (claim.space_tags || []).includes(tag) || (claim.topic_tags || []).includes(tag)
            || (claim.process_stage || "").includes(tag) || claim.stance === tag) &&
          (!stance || claim.stance === stance) &&
          (!authorStance || (claim.author_stance || ({ "明确推荐": "赞成", "明确不推荐": "反对" }[claim.stance] || "未明确")) === authorStance) &&
          (!contentType || (claim.content_type || "旧版未分类") === contentType) &&
          (!query || contains([claim.object_name, claim.original_conclusion, claim.conditions,
            ...(claim.original_reasons || [])].join(" "), query)));
        result = { ...page(items, params, "claims", 50), facets: data.knowledge_facets };
        break;
      }
      case "/api/progress-summary":
        result = { counts: data.progress_counts };
        break;
      case "/api/progress-videos": {
        const state = params.get("state");
        const items = data.videos.filter((video) => !state || state === "全部" || video.progress_state === state);
        result = page(items.map(summary), params, "videos", 30);
        break;
      }
      default: {
        const match = url.pathname.match(/^\/api\/videos\/([^/]+)$/);
        if (!match || params.has("include_runs")) throw new Error("公开预览不提供管理接口。");
        const video = data.videos.find((item) => item.id === decodeURIComponent(match[1]));
        if (!video) throw new Error("视频不存在或未公开。");
        result = { video, claims: data.claims.filter((claim) => claim.video_id === video.id) };
      }
    }
    // The management UI must never be able to mutate the cached public dataset.
    return structuredClone(result);
  }

  Object.defineProperty(window, "DECOR_PUBLIC_LIBRARY", { value: Object.freeze({ snapshot, get }) });
})();
