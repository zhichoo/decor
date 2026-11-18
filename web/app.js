const stages = [
  { name: "准备阶段", desc: "确定预算、居住需求、装修方式和资料收集范围。", risk: "中" },
  { name: "收房验房", desc: "确认墙地面、门窗、水电、空鼓、渗漏等基础质量。", risk: "高" },
  { name: "设计规划", desc: "确定平面布局、动线、收纳、电器点位和材料方向。", risk: "中" },
  { name: "拆改阶段", desc: "处理非承重墙、门洞、墙体修补和垃圾清运。", risk: "高" },
  { name: "水电阶段", desc: "决定后期用电安全、维修成本和空间使用体验。", risk: "高" },
  { name: "防水阶段", desc: "覆盖卫生间、厨房、阳台等涉水区域的防水施工和闭水测试。", risk: "高" },
  { name: "瓦工阶段", desc: "瓷砖铺贴、找平、地漏坡度、墙地砖对缝和美缝基础。", risk: "中" },
  { name: "木工阶段", desc: "吊顶、背景墙、局部造型和基层处理。", risk: "中" },
  { name: "油工阶段", desc: "墙面基层、腻子、乳胶漆、阴阳角和开裂控制。", risk: "中" },
  { name: "主材安装", desc: "门、地板、踢脚线、石材、窗台等主材进场安装。", risk: "中" },
  { name: "定制柜安装", desc: "橱柜、衣柜、玄关柜、浴室柜和收口细节。", risk: "高" },
  { name: "厨卫安装", desc: "洁具、龙头、台盆、马桶、花洒、烟机灶具和水槽安装。", risk: "中" },
  { name: "灯具开关五金", desc: "照明层次、开关逻辑、门锁、拉手、挂件和收边。", risk: "低" },
  { name: "家电家具软装", desc: "家电安装、家具进场、窗帘、地毯和软装搭配。", risk: "低" },
  { name: "开荒保洁", desc: "硬装结束后的深度清洁、胶痕处理和成品保护拆除。", risk: "低" },
  { name: "通风除醛", desc: "空气质量检测、通风策略、温湿度和入住前安全确认。", risk: "中" },
  { name: "入住验收", desc: "全屋设备、收口、渗漏、开关、门窗和售后清单。", risk: "中" },
];

const overviewProcessNodes = ["来源账号", "入库视频", "文案采集", "观点提取", "知识入库"];

const DEFAULT_LOCAL_API_ORIGIN = "http://127.0.0.1:4189";

function normalizeApiOrigin(value) {
  return String(value || "").trim().replace(/\/api\/?$/, "").replace(/\/+$/, "");
}

function resolveApiBase() {
  if (window.DECOR_PUBLIC_LIBRARY) return `${window.location.origin}/api`;
  const params = new URLSearchParams(window.location.search);
  const explicitApiOrigin = normalizeApiOrigin(params.get("api") || window.ZHUANGXIU_API_ORIGIN);
  if (explicitApiOrigin) {
    localStorage.setItem("zhuangxiuApiOrigin", explicitApiOrigin);
    return `${explicitApiOrigin}/api`;
  }
  const storedApiOrigin = normalizeApiOrigin(localStorage.getItem("zhuangxiuApiOrigin"));
  if (window.location.protocol === "http:" || window.location.protocol === "https:") {
    const currentOrigin = normalizeApiOrigin(window.location.origin);
    if (currentOrigin !== DEFAULT_LOCAL_API_ORIGIN) return `${currentOrigin}/api`;
    if (storedApiOrigin) return `${storedApiOrigin}/api`;
    return `${DEFAULT_LOCAL_API_ORIGIN}/api`;
  }
  if (storedApiOrigin) return `${storedApiOrigin}/api`;
  return `${DEFAULT_LOCAL_API_ORIGIN}/api`;
}

const API_BASE = resolveApiBase();
const API_CACHE_KEY = `zhuangxiuApiSnapshot:v9${window.DECOR_PUBLIC_LIBRARY ? `:${window.DECOR_PUBLIC_LIBRARY.snapshot}` : ""}`;
const API_CACHE_MAX_AGE = 10 * 60 * 1000;

const fallbackVideos = [];


const knowledgeCategoryGroups = [
  {
    title: "范围",
    items: [{ type: "all", value: "全部", label: "全部观点", meta: "所有知识卡" }],
  },
  {
    title: "按装修阶段",
    items: stages.map((stage) => ({ type: "stage", value: stage.name, label: stage.name, meta: "装修阶段" })),
  },
  {
    title: "按空间",
    items: ["厨房", "卫生间", "客厅", "卧室", "阳台", "全屋"].map((value) => ({ type: "tag", value, label: value, meta: "空间标签" })),
  },
  {
    title: "按主题",
    items: ["预算", "避坑", "环保", "材料", "品牌", "维修", "照明", "家电"].map((value) => ({ type: "tag", value, label: value, meta: "主题标签" })),
  },
  {
    title: "按作者态度",
    items: ["赞成", "反对", "中性陈述", "未明确"].map((value) => ({ type: "authorStance", value, label: value === "未明确" ? "态度未明确" : `作者${value}`, meta: "来源态度，非系统评级" })),
  },
  {
    title: "按内容类型",
    items: ["选购建议", "施工做法", "验收要求", "价格信息", "个人体验", "中性说明", "其他", "未分类"].map((value) => ({ type: "contentType", value, label: value, meta: "观点主要类型" })),
  },
];
const viewTitles = {
  overview: "装修全流程知识地图",
  sources: "视频来源",
  videos: "视频列表",
  detail: "视频详情",
  progress: "处理进度",
  knowledge: "知识库",
  guide: "装修指南",
  deleted: "回收站",
  settings: "设置",
};
const viewNames = new Set(Object.keys(viewTitles));

let transcriptSettings = { provider: null, loading: false, busy: false, health: null, message: "", error: "" };
let transcriptSettingsRequest = 0;



function getInitialView() {
  const hashView = window.location.hash.replace(/^#/, "");
  return viewNames.has(hashView) ? hashView : "overview";
}

let videos = fallbackVideos;
let progressVideos = [];
let sources = [];
let knowledgeClaims = [];
let deletedItems = { videos: [], claims: [], videoTotal: 0, claimTotal: 0, loading: false, error: "" };
let activeDeletedTab = "videos";
let deletedLoadRequestId = 0;
let deletedSessionVersion = 0;
// Keep deleted previews out of the active-video cache and pagination.
const deletedVideoDetails = new Map();
const retainedSourceDetails = new Map();
const videoDetailVersions = new Map();
let activeView = getInitialView();
let selectedVideoId = videos[0]?.id || null;
const transcriptEdits = new Map();
const videoExtractions = new Map();
const videoTranscriptions = new Map();
const detailedVideos = new Map();
let activeSourceFilter = null;
let activeVideoPlatform = "全部";
let activeVideoCreator = "全部";
let activeKnowledgeCategory = { type: "all", value: "全部" };
let activeKnowledgeGroupTitle = "范围";
let activeProgressFilter = "全部";
let ingestSubmitMode = "batch";
let ingestSubmitting = false;
let queueStatusTimer = null;
let activeProgressLogVideoId = null;
let lastQueueStatus = null;
let queueLogMode = "global";
let apiLoadState = { status: "loading", error: "", attempts: 0 };
let apiHealthState = { ok: true, dbAvailable: true, dbMessage: "" };
let apiStats = { sourceCount: null, videoCount: null, transcriptCount: null, claimCount: null };
let videoFacets = null;
let knowledgeFacets = null;
let adminSession = { authenticated: false, configured: false };
let adminSessionLoaded = false;
let sourcePerformance = { status: "idle", sources: new Map(), reasonLabels: {}, error: "" };
let sourcePerformanceRequestId = 0;
let exclusionRequestId = 0;
const expandedSourcePerformance = new Set();
const expandedProgressNotes = new Set();
let progressSummary = null;
// Views that only a logged-in admin can open; visitors fall back to the overview.
const ADMIN_VIEWS = new Set(["deleted", "settings", "progress"]);
let progressLoadedForAdmin = false;
let apiLoadRequestId = 0;
let videoLoadRequestId = 0;
let videoListRepairPending = false;
let videoListRepairAttemptId = -1;
let knowledgeLoadRequestId = 0;
let douyinLoginStatus = { status: "idle", message: "未检查", running: false, logged_in: null };
let douyinLoginChecking = false;
let douyinLoginRequest = null;
let douyinLoginRequestId = 0;
let douyinLoginTimer = null;
let knowledgeSearchTimer = null;
let autoLoadObserver = null;
let navigationEntryKey = null;
const navigationPositions = new Map();
let pendingKnowledgeReturnPosition = null;
let detailLoadError = "";
let detailLoadingId = null;
let detailLoadRequestId = 0;
let queueLogFollowState = { global: true };
let adminLoginBusy = false;
let adminLoginReturnFocus = null;

const pageTitle = document.querySelector("#page-title");
const openIngestButton = document.querySelector("#open-ingest");
const ingestPanel = document.querySelector("#ingest-panel");
const ingestForm = document.querySelector("#ingest-form");
const ingestMessage = document.querySelector("#ingest-message");
const queueMessage = document.querySelector("#queue-message");
const progressMessage = document.querySelector("#progress-message");
const queueLogPanel = document.querySelector("#queue-log-panel");
const queueLogBody = document.querySelector("#queue-log-body");
const queueLogMeta = document.querySelector("#queue-log-meta");
const progressProcessPendingButton = document.querySelector("#progress-process-pending");
const adminPanel = document.querySelector("#admin-panel");
const adminStatus = document.querySelector("#admin-status");
const adminLoginButton = document.querySelector("#admin-login-button");
const adminLogoutButton = document.querySelector("#admin-logout-button");
const adminLoginModal = document.querySelector("#admin-login-modal");
const adminLoginForm = document.querySelector("#admin-login-form");
const adminLoginPassword = document.querySelector("#admin-login-password");
const adminLoginSubmit = document.querySelector("#admin-login-submit");
const adminLoginMessage = document.querySelector("#admin-login-message");
const VIDEO_PAGE_SIZE = 30;
const KNOWLEDGE_PAGE_SIZE = 50;
let videoPageState = { total: 0, limit: VIDEO_PAGE_SIZE, offset: 0, hasMore: false, loading: false, error: "" };
let progressPageState = { total: 0, limit: VIDEO_PAGE_SIZE, offset: 0, hasMore: false, loading: false, error: "" };
let knowledgePageState = { total: 0, limit: KNOWLEDGE_PAGE_SIZE, offset: 0, hasMore: false, loading: false, error: "" };

const autoLoadTargets = {
  "load-more-videos": {
    view: "videos",
    canLoad: () => videoPageState.hasMore && !videoPageState.loading,
    load: () => loadVideoPage({ append: true }),
  },
  "load-more-progress": {
    view: "progress",
    canLoad: () => progressPageState.hasMore && !progressPageState.loading,
    load: () => loadProgressPage({ append: true }),
  },
  "load-more-knowledge": {
    view: "knowledge",
    canLoad: () => knowledgePageState.hasMore && !knowledgePageState.loading,
    load: () => loadKnowledgePage({ append: true }),
  },
};
function getAllClaims() {
  if (knowledgeClaims.length) return knowledgeClaims;
  return videos.flatMap((video) =>
    (video.claims || []).map((claim, index) => ({
      ...claim,
      id: `${video.id}-${index}`,
      videoId: video.id,
      videoTitle: video.title,
      creator: video.creator,
      platform: video.platform,
      sourceUrl: video.sourceUrl,
    })),
  );
}

function normalizeCount(value) {
  if (value == null || typeof value === "boolean" || String(value).trim() === "") return null;
  const count = Number(value);
  return Number.isFinite(count) && count >= 0 ? count : null;
}

function normalizeApiStats(stats = {}) {
  return {
    sourceCount: normalizeCount(stats.source_count),
    videoCount: normalizeCount(stats.video_count),
    transcriptCount: normalizeCount(stats.transcript_count),
    claimCount: normalizeCount(stats.claim_count),
  };
}

function firstKnownCount(...values) {
  return values.find((value) => Number.isFinite(value)) ?? 0;
}

function getClaimTotal() {
  const claims = getAllClaims();
  return firstKnownCount(knowledgeFacets?.total, apiStats.claimCount, claims.length || null, videos.reduce((sum, video) => sum + (video.claimCount || 0), 0));
}

function getPipeline() {
  const claims = getAllClaims();
  const sourceCount = firstKnownCount(apiStats.sourceCount, sources.length || new Set(videos.map((video) => video.creator).filter(Boolean)).size);
  return [
    ["来源账号", sourceCount],
    ["入库视频", firstKnownCount(apiStats.videoCount, videos.length)],
    ["已有文案", firstKnownCount(apiStats.transcriptCount, videos.filter(hasVideoTranscript).length)],
    ["观点入库", firstKnownCount(apiStats.claimCount, claims.length || null, videos.reduce((sum, video) => sum + (video.claimCount || 0), 0))],
  ];
}

function getVideoPublishTimestamp(video) {
  const value = video.publishTime || "";
  const timestamp = Date.parse(String(value).replace(" ", "T"));
  return Number.isNaN(timestamp) ? 0 : timestamp;
}

function formatEpochDateTime(value) {
  const timestamp = Number(value);
  if (!Number.isFinite(timestamp) || timestamp <= 0) return "未记录";
  const date = new Date(timestamp * 1000);
  const pad = (part) => String(part).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

function getVideoProgressTimeItems(video) {
  return [
    { label: "发布时间", value: video.publishTime || "未提及" },
    { label: "状态更新时间", value: formatEpochDateTime(video.updatedAt) },
  ];
}

function sortVideosByPublishTime(items) {
  return [...items].sort((a, b) => getVideoPublishTimestamp(b) - getVideoPublishTimestamp(a));
}

function normalizeApiClaim(claim) {
  const reasons = Array.isArray(claim.original_reasons) ? claim.original_reasons : claim.original_reasons ? [claim.original_reasons] : [];
  const alternatives = Array.isArray(claim.alternatives) ? claim.alternatives.join("；") : claim.alternatives || "";
  return {
    id: claim.id,
    videoId: claim.video_id,
    sourceVideoIsPromotional: Boolean(claim.source_video_is_promotional),
    object: claim.object_name,
    stance: claim.stance,
    authorStance: claim.author_stance || ({ "明确推荐": "赞成", "明确不推荐": "反对" }[claim.stance] || "未明确"),
    contentType: !claim.content_type || claim.content_type === "旧版未分类" ? "未分类" : claim.content_type,
    sourceQuotes: Array.isArray(claim.source_quotes) ? claim.source_quotes : [],
    legacyContext: !claim.author_stance || !claim.content_type,
    stage: claim.process_stage,
    tags: [...(claim.space_tags || []), ...(claim.topic_tags || [])].filter((tag) => tag && tag !== "未提及"),
    conclusion: claim.original_conclusion,
    reasons,
    conditions: claim.conditions,
    alternatives: alternatives || "未提及",
    priceInfo: claim.price_info,
    sourceUrl: claim.source_video_url,
    relationCounts: claim.relation_counts || {},
    creator: claim.creator || "",
    videoTitle: claim.video_title || "",
  };
}

function normalizeApiVideo(video) {
  const transcriptText = video.transcript_text || "";
  const transcriptLength = Number(video.transcript_length || transcriptText.trim().length || 0);
  return {
    id: video.id,
    title: video.title,
    creator: video.creator,
    sourceId: video.source_id,
    platform: video.platform,
    sourceUrl: video.source_url,
    shareUrl: video.share_url,
    shareText: video.share_text,
    status: video.status,
    sourceReadOnly: Boolean(video.source_read_only),
    adReview: video.ad_review || null,
    publishTime: video.published_at || "未提及",
    createdAt: video.created_at || null,
    updatedAt: video.updated_at || null,
    transcriptCreatedAt: video.transcript_created_at || null,
    transcriptJob: video.transcript_job || null,
    lastRetryAt: video.last_retry_at || null,
    claimCount: video.claim_count || 0,
    excludedClaimCount: Number(video.excluded_claim_count || 0),
    retryCount: video.retry_count || 0,
    lastError: video.last_error || "",
    hasTranscript: Boolean(video.has_transcript || transcriptLength > 0),
    transcriptLength,
    transcript: transcriptText,
    detailLoaded: Object.hasOwn(video, "transcript_text"),
    claims: Array.isArray(video.claims) ? video.claims.map(normalizeApiClaim) : [],
  };
}

function hasVideoTranscript(video) {
  return Boolean(video?.hasTranscript || video?.transcriptLength > 0);
}

function getVideoTranscriptLabel(video) {
  if (!hasVideoTranscript(video)) return "待提取";
  return video.transcriptLength > 0 ? `${video.transcriptLength} 字` : "已保存";
}

const VIDEO_STATUS_LABELS = {
  created: "已创建",
  transcript_pending: "待提取文案",
  transcript_saved: "文案已保存",
  claims_extracted: "观点已提取",
  claims_filtered: "观点已过滤",
  claims_seeded: "种子观点已入库",
  transcript_failed: "文稿转写失败",
  completed: "已完成",
  filtered: "已过滤",
  empty: "暂无状态",
};

function getVideoStatusLabel(status) {
  return VIDEO_STATUS_LABELS[status] || "未知状态";
}

function videoBadgeSvg(name) {
  const paths = {
    video: '<rect x="3" y="4" width="18" height="16" rx="3"/><path d="m10 8 6 4-6 4Z"/>',
    document: '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8Z"/><path d="M14 2v6h6M8 12h8M8 16h5"/>',
    claims: '<path d="M21 11.5a8.5 8.5 0 0 1-8.5 8.5H4l-2 2V11.5A8.5 8.5 0 0 1 10.5 3H12"/><path d="m14 4 2-2 2 2-2 2ZM17 10l2-2 2 2-2 2ZM7 11h5M7 15h8"/>',
    promotion: '<path d="m3 10 14-6v16L3 14ZM17 9l4-2M17 15l4 2M7 16l1 5h4l-2-4"/>',
    check: '<path d="m5 12 4 4L19 6"/>',
    cross: '<path d="m7 7 10 10M17 7 7 17"/>',
    running: '<path d="M20 12a8 8 0 1 1-8-8"/>',
    filter: '<path d="M3 4h18l-7 8v7l-4 2v-9Z"/>',
    clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    warning: '<path d="m12 3 10 18H2ZM12 9v4M12 17h.01"/>',
    delete: '<path d="M3 6h18M9 6V4h6v2M5 6l1 14h12l1-14M10 10v6M14 10v6"/>',
    support: '<path d="M7 10v11M15 6l-1 4h5a2 2 0 0 1 2 2.5l-2 7A2 2 0 0 1 17 21H5a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2h2l5-7a3 3 0 0 1 3 3Z"/>',
    oppose: '<path d="M7 14V3M15 18l-1-4h5a2 2 0 0 0 2-2.5l-2-7A2 2 0 0 0 17 3H5a2 2 0 0 0-2 2v7a2 2 0 0 0 2 2h2l5 7a3 3 0 0 0 3-3Z"/>',
    statement: '<path d="M21 12a9 9 0 0 1-9 9H3l2.6-2.6A9 9 0 1 1 21 12Z"/><path d="M8 12h8"/>',
    unknown: '<circle cx="12" cy="12" r="9"/><path d="M9.5 9a2.5 2.5 0 1 1 4.3 1.7c-1 .6-1.8 1.1-1.8 2.3M12 17h.01"/>',
  };
  return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths[name] || ""}</svg>`;
}

function renderVideoStateBadge(kind, label, state, description) {
  const stateIcon = state === "running" ? "running" : state === "done" ? "check" : "cross";
  return `<span class="video-state-badge" data-state="${state}" title="${escapeAttr(description)}" aria-label="${escapeAttr(description)}">${videoBadgeSvg(kind)}<span>${label}</span><span class="video-state-mark">${videoBadgeSvg(stateIcon)}</span></span>`;
}

function getPromotionPresentation(video) {
  const decision = video?.adReview?.decision;
  if (decision === "advertising") return { label: "推广", icon: "promotion", state: "promotion" };
  if (["uncertain", "error"].includes(decision)) return { label: "疑似推广", icon: "promotion", state: "uncertain" };
  if (decision === "not_ad") return { label: "普通内容", icon: "check", state: "neutral" };
  return { label: "未识别", icon: "clock", state: "neutral" };
}

function renderAdBadge(video) {
  const promotion = getPromotionPresentation(video);
  if (promotion.state === "neutral") return "";
  return `<span class="video-state-badge video-promotion-badge" data-state="${promotion.state}" title="${escapeAttr(getVideoReasonLabel(video))}">${videoBadgeSvg(promotion.icon)}<span>${promotion.label}</span></span>`;
}

function getVideoReasonLabel(video) {
  if (video?.adReview?.decision === "advertising") return `推广：${String(video.adReview.reason || "").replaceAll("广告", "推广")}；跳过自动提取，可手动提取。`;
  if (["uncertain", "error"].includes(video?.adReview?.decision)) return `疑似推广：${String(video.adReview.reason || "").replaceAll("广告", "推广")}；暂停自动提取。`;
  const reason = String(video?.lastError || "").trim();
  if (!reason) return "";
  if (reason.startsWith("deepseek_timeout:") || reason.includes("Operation timed out")) {
    return "模型超时，文案和知识卡已保留，可重试。";
  }
  if (video.status === "claims_filtered") return `无可用观点：${reason.replace(/^无有效内容[:：]\s*/, "")}`;
  if (video.status === "transcript_failed") return `文案失败：${reason}`;
  return `处理原因：${reason}`;
}

const SOURCE_STATUS_LABELS = {
  active: "启用中",
  inactive: "已停用",
};

function getSourceStatusLabel(status) {
  return SOURCE_STATUS_LABELS[status] || "未知状态";
}

function normalizeKnowledgeClaim(claim) {
  const normalized = normalizeApiClaim(claim);
  return {
    ...normalized,
    id: claim.id,
    videoId: claim.video_id,
    videoTitle: claim.video_title || "",
    creator: claim.creator || "",
    platform: claim.platform || "",
    sourceUrl: claim.source_video_url,
  };
}

function readApiCache() {
  try {
    const snapshot = JSON.parse(sessionStorage.getItem(API_CACHE_KEY) || "null");
    if (!snapshot || snapshot.apiBase !== API_BASE || !snapshot.timestamp) return null;
    if (Date.now() - snapshot.timestamp > API_CACHE_MAX_AGE) return null;
    if (!Array.isArray(snapshot.sources) || !Array.isArray(snapshot.videos) || !Array.isArray(snapshot.knowledgeClaims)) return null;
    return snapshot;
  } catch (error) {
    console.info("API cache read failed:", error.message);
    return null;
  }
}

function writeApiCache() {
  try {
    sessionStorage.setItem(
      API_CACHE_KEY,
      JSON.stringify({
        apiBase: API_BASE,
        timestamp: Date.now(),
        sources,
        videos: activeSourceFilter || activeVideoPlatform !== "全部" || activeVideoCreator !== "全部" ? [] : videos,
        videoPageState,
        selectedVideoId,
        knowledgeClaims,
        apiStats,
        videoFacets,
        knowledgeFacets,
        progressSummary,
      }),
    );
  } catch (error) {
    console.info("API cache write failed:", error.message);
  }
}

function applyApiSnapshot(snapshot) {
  sources = snapshot.sources;
  videos = sortVideosByPublishTime(snapshot.videos);
  if (videos.length && snapshot.videoPageState) {
    videoPageState = { ...snapshot.videoPageState, loading: false, error: "" };
  }
  knowledgeClaims = snapshot.knowledgeClaims;
  apiStats = snapshot.apiStats || apiStats;
  videoFacets = snapshot.videoFacets || null;
  knowledgeFacets = snapshot.knowledgeFacets || null;
  progressSummary = snapshot.progressSummary || progressSummary;
  if (activeView === "detail" && snapshot.selectedVideoId) selectedVideoId = history.state?.videoId || snapshot.selectedVideoId;
  if (activeSourceFilter && !sources.some((source) => source.id === activeSourceFilter.id)) {
    activeSourceFilter = null;
  }
  if (!selectedVideoId || (activeView !== "detail" && !videos.some((video) => video.id === selectedVideoId))) {
    selectedVideoId = videos[0]?.id || null;
  }
}

function applyApiHealth(payload = {}) {
  apiHealthState = {
    ok: true,
    dbAvailable: payload.db_available !== false,
    dbMessage: payload.db_message || "",
  };
  if (apiHealthState.dbAvailable === false) {
    throw new Error(`数据库当前不可用：${apiHealthState.dbMessage || "请稍后重试"}`);
  }
}

function adminActionAttributes(blocked = false) {
  return `data-admin-required data-admin-blocked="${blocked}" ${!adminSession.authenticated || blocked ? "disabled" : ""} ${!adminSession.authenticated ? 'title="请先登录管理员"' : ""}`;
}

function syncAdminActionButtons() {
  document.documentElement.dataset.adminAuthenticated = String(adminSession.authenticated);
  document.querySelectorAll("[data-admin-required]").forEach((button) => {
    button.disabled = !adminSession.authenticated || button.dataset.adminBusy === "true" || button.dataset.adminBlocked === "true";
    if (!adminSession.authenticated) {
      button.title = "请先登录管理员";
    } else {
      button.removeAttribute("title");
    }
  });
}

function setAdminActionBusy(button, busy) {
  button.dataset.adminBusy = String(busy);
  syncAdminActionButtons();
}

function requireAdminAction() {
  if (window.DECOR_PUBLIC_LIBRARY) throw new Error("公开预览仅支持浏览，不支持修改或删除。");
  if (!adminSession.authenticated) throw new Error("请先登录管理员后再操作。");
}

function renderAdminSession() {
  syncAdminActionButtons();
  if (openIngestButton) openIngestButton.hidden = activeView !== "sources" || !adminSession.authenticated;
  if (!adminSession.authenticated) {
    deletedSessionVersion += 1;
    deletedLoadRequestId += 1;
    deletedItems = { videos: [], claims: [], videoTotal: 0, claimTotal: 0, loading: false, error: "" };
    deletedVideoDetails.clear();
    renderDeleted();
    progressLoadedForAdmin = false;
    progressSummary = null;
    progressVideos = [];
    progressPageState = { total: 0, limit: VIDEO_PAGE_SIZE, offset: 0, hasMore: false, loading: false, error: "" };
    renderProgress();
    if (document.querySelector('#detail-view[data-deleted-preview="true"]')) renderDetail();
    if (adminSessionLoaded && activeView === "detail" && history.state?.deletedVideo) setView("overview");
    clearVideoExclusions();
    sourcePerformanceRequestId += 1;
    sourcePerformance = { status: "idle", sources: new Map(), reasonLabels: {}, error: "" };
    expandedSourcePerformance.clear();
    // Remove private source content even when the sources view is currently hidden.
    renderSources();
    if (ingestPanel) ingestPanel.hidden = true;
    openIngestButton?.setAttribute("aria-expanded", "false");
    if (ADMIN_VIEWS.has(activeView)) setView(activeView);
  } else if (!progressLoadedForAdmin && apiLoadState.status === "ready") {
    // Progress data is admin-only, so it loads once the session is confirmed.
    progressLoadedForAdmin = true;
    loadProgressSummary();
    loadProgressPage();
  }
  if (!adminPanel || !adminStatus || !adminLoginButton || !adminLogoutButton) return;
  adminPanel.hidden = !adminSessionLoaded || Boolean(adminSession.read_only) || Boolean(adminSession.error);
  if (adminSession.read_only) closeAdminLoginModal();
  adminPanel.dataset.authenticated = adminSession.authenticated ? "true" : "false";
  if (!adminSession.configured) {
    adminStatus.textContent = "管理员未配置";
    adminLoginButton.hidden = false;
    adminLogoutButton.hidden = true;
  } else {
    adminStatus.textContent = adminSession.authenticated ? "管理员已登录" : "管理员未登录";
    adminLoginButton.hidden = adminSession.authenticated;
    adminLogoutButton.hidden = !adminSession.authenticated;
  }
  renderIfActive("sources", "videos", "progress", "detail", "knowledge", "deleted", "settings");
  if (activeView === "sources" && sourcePerformance.status === "idle") loadSourcePerformance();
}

async function loadSourcePerformance() {
  if (!adminSession.authenticated || adminSession.read_only || window.DECOR_PUBLIC_LIBRARY
      || sourcePerformance.status === "loading") return;
  const requestId = ++sourcePerformanceRequestId;
  sourcePerformance = { ...sourcePerformance, status: "loading", error: "" };
  if (activeView === "sources") renderSources();
  try {
    const response = await fetch(`${API_BASE}/admin/source-performance`, { credentials: "include", cache: "no-store" });
    if (requestId !== sourcePerformanceRequestId || !adminSession.authenticated) return;
    if (response.status === 401) {
      adminSession = { ...adminSession, authenticated: false };
      renderAdminSession();
      return;
    }
    if (!response.ok) throw new Error("暂时无法读取，请重试");
    const payload = await response.json();
    if (requestId !== sourcePerformanceRequestId || !adminSession.authenticated) return;
    sourcePerformance = { status: "ready", sources: new Map((payload.sources || []).map(item => [item.source_id, item])),
      reasonLabels: payload.reason_labels || {}, error: "" };
  } catch (error) {
    if (requestId !== sourcePerformanceRequestId || !adminSession.authenticated) return;
    sourcePerformance = { ...sourcePerformance, status: "error", error: "暂时无法读取，请重试" };
  }
  if (activeView === "sources") renderSources();
}

async function loadAdminSession() {
  try {
    adminSession = await fetchApiJson("/admin/session");
  } catch (error) {
    adminSession = { authenticated: false, configured: false, error: error.message };
  }
  adminSessionLoaded = true;
  renderAdminSession();
  if (ADMIN_VIEWS.has(window.location.hash.slice(1))) syncViewFromHash();
  if (adminSession.authenticated && activeView === "detail" && history.state?.deletedVideo) loadSelectedVideoDetail();
  return adminSession;
}

async function fetchDeletedJson(path) {
  requireAdminAction();
  const sessionVersion = deletedSessionVersion;
  const response = await fetch(`${API_BASE}${path}`, { credentials: "include", cache: "no-store" });
  if (sessionVersion !== deletedSessionVersion || !adminSession.authenticated) throw new Error("管理员会话已变化");
  if (response.status === 401) {
    adminSession = { ...adminSession, authenticated: false };
    renderAdminSession();
    throw new Error("请重新登录管理员");
  }
  if (!response.ok) throw new Error("读取失败，请重试");
  return response.json();
}

async function loadDeletedItems({ append = false, preserveLoaded = false } = {}) {
  if (!adminSession.authenticated) {
    deletedItems = { ...deletedItems, videos: [], claims: [], videoTotal: 0, claimTotal: 0, loading: false, error: "" };
    renderDeleted();
    return;
  }
  const requestId = ++deletedLoadRequestId;
  const offset = append ? Math.max(deletedItems.videos.length, deletedItems.claims.length) : 0;
  const targetCount = preserveLoaded ? Math.max(50, deletedItems.videos.length, deletedItems.claims.length) : 50;
  deletedItems = { ...deletedItems, loading: true, error: "" };
  renderDeleted();
  try {
    const payload = await fetchDeletedJson(`/admin/deleted${offset ? buildQueryString({ offset }) : ""}`);
    // Refill the loaded range after deletion so the current scroll position stays reachable.
    for (let nextOffset = 50; !append && nextOffset < targetCount; nextOffset += 50) {
      if (requestId !== deletedLoadRequestId || !adminSession.authenticated) return;
      if (nextOffset >= Math.max(payload.video_total || 0, payload.claim_total || 0)) break;
      const next = await fetchDeletedJson(`/admin/deleted${buildQueryString({ offset: nextOffset })}`);
      payload.videos = [...(payload.videos || []), ...(next.videos || [])];
      payload.claims = [...(payload.claims || []), ...(next.claims || [])];
      payload.video_total = next.video_total;
      payload.claim_total = next.claim_total;
    }
    if (requestId !== deletedLoadRequestId || !adminSession.authenticated) return;
    const merge = (previous, received) => append ? [...new Map([...previous, ...received].map(item => [item.id, item])).values()] : received;
    deletedItems = {
      videos: merge(deletedItems.videos, payload.videos || []),
      claims: merge(deletedItems.claims, payload.claims || []),
      videoTotal: normalizeCount(payload.video_total) || 0,
      claimTotal: normalizeCount(payload.claim_total) || 0,
      loading: false,
      error: "",
      loaded: true,
    };
  } catch (error) {
    if (requestId !== deletedLoadRequestId || !adminSession.authenticated) return;
    deletedItems = { ...deletedItems, loading: false, error: error.message };
  }
  renderDeleted();
}

function isDeletedVideoDetail() {
  return activeView === "detail" && Boolean(history.state?.deletedVideo);
}

async function loadDeletedVideoDetail(videoId) {
  const sessionVersion = deletedSessionVersion;
  const detail = await fetchDeletedJson(`/admin/deleted/videos/${encodeURIComponent(videoId)}`);
  if (sessionVersion !== deletedSessionVersion || !adminSession.authenticated) return;
  const video = normalizeApiVideo({ ...detail.video, claims: detail.claims, claim_count: detail.claims.length });
  deletedVideoDetails.set(videoId, video);
  return video;
}

function setAdminLoginMessage(message = "", type = "") {
  if (!adminLoginMessage) return;
  adminLoginMessage.textContent = message;
  if (type) {
    adminLoginMessage.dataset.type = type;
  } else {
    delete adminLoginMessage.dataset.type;
  }
}

function setAdminLoginBusy(busy) {
  adminLoginBusy = busy;
  if (adminLoginSubmit) {
    adminLoginSubmit.disabled = busy;
    adminLoginSubmit.textContent = busy ? "登录中..." : "登录";
  }
  if (adminLoginPassword) {
    adminLoginPassword.disabled = busy;
  }
  if (adminLoginButton) {
    adminLoginButton.disabled = busy;
  }
  document.querySelectorAll("[data-admin-login-close]").forEach((button) => {
    button.disabled = busy;
  });
}

function closeAdminLoginModal() {
  if (!adminLoginModal || adminLoginBusy) return;
  adminLoginModal.hidden = true;
  if (adminLoginPassword) {
    adminLoginPassword.value = "";
  }
  setAdminLoginMessage();
  document.body.classList.remove("modal-open");
  if (adminLoginReturnFocus && typeof adminLoginReturnFocus.focus === "function") {
    adminLoginReturnFocus.focus();
  }
  adminLoginReturnFocus = null;
}

function openAdminLoginModal(trigger = document.activeElement) {
  if (!adminSessionLoaded || adminSession.read_only) return;
  if (!adminLoginModal || !adminLoginPassword) return;
  adminLoginReturnFocus = trigger instanceof HTMLElement ? trigger : document.activeElement;
  adminLoginModal.hidden = false;
  document.body.classList.add("modal-open");
  adminLoginPassword.value = "";
  setAdminLoginMessage();
  window.requestAnimationFrame(() => adminLoginPassword.focus());
}

async function submitAdminLogin(password) {
  if (!adminSessionLoaded || adminSession.read_only) return false;
  const cleanedPassword = String(password || "");
  if (!cleanedPassword) {
    setAdminLoginMessage("请输入管理员密码。", "error");
    adminLoginPassword?.focus();
    return false;
  }
  setAdminLoginBusy(true);
  try {
    adminSession = await postJson(`${API_BASE}/admin/login`, { password: cleanedPassword });
    renderAdminSession();
    if (activeView === "deleted") loadDeletedItems();
    setAdminLoginBusy(false);
    closeAdminLoginModal();
    return true;
  } catch (error) {
    setAdminLoginMessage(`登录失败：${error.message}`, "error");
    setAdminLoginBusy(false);
    adminLoginPassword?.focus();
    return false;
  }
}

async function loginAdmin(trigger) {
  if (adminSession.authenticated) return true;
  openAdminLoginModal(trigger);
  return false;
}

async function logoutAdmin() {
  adminLogoutButton.disabled = true;
  try {
    adminSession = await postJson(`${API_BASE}/admin/logout`, {});
    renderAdminSession();
    if (activeView === "deleted") loadDeletedItems();
  } catch (error) {
    alert(`退出失败：${error.message}`);
  } finally {
    adminLogoutButton.disabled = false;
  }
}

async function restoreVideo(videoId) {
  if (!adminSession.authenticated) {
    await loginAdmin();
    if (!adminSession.authenticated) return;
  }
  await postJson(`${API_BASE}/videos/${videoId}/restore`, {});
  await Promise.allSettled([loadApiData(), loadDeletedItems()]);
}

async function restoreClaim(claimId) {
  if (!adminSession.authenticated) {
    await loginAdmin();
    if (!adminSession.authenticated) return;
  }
  await postJson(`${API_BASE}/claims/${claimId}/restore`, {});
  await Promise.allSettled([loadKnowledgePage(), loadDeletedItems()]);
}

function updateVideoPageState(payload = {}, append = false) {
  if (Array.isArray(payload.facets?.platforms) && Array.isArray(payload.facets?.creators)) {
    videoFacets = payload.facets;
    apiStats.videoCount = normalizeCount(payload.facets.total) ?? apiStats.videoCount;
  }
  const received = Array.isArray(payload.videos) ? payload.videos.length : 0;
  videoPageState = {
    total: normalizeCount(payload.total) ?? (append ? Math.max(videoPageState.total, videos.length) : received),
    limit: normalizeCount(payload.limit) ?? VIDEO_PAGE_SIZE,
    offset: (normalizeCount(payload.offset) ?? 0) + received,
    hasMore: Boolean(payload.has_more),
    loading: false,
    error: "",
  };
}

function updateProgressPageState(payload = {}, append = false) {
  const received = Array.isArray(payload.videos) ? payload.videos.length : 0;
  progressPageState = {
    total: normalizeCount(payload.total) ?? (append ? Math.max(progressPageState.total, progressVideos.length) : received),
    limit: normalizeCount(payload.limit) ?? VIDEO_PAGE_SIZE,
    offset: (normalizeCount(payload.offset) ?? 0) + received,
    hasMore: Boolean(payload.has_more),
    loading: false,
    error: "",
  };
}

function updateKnowledgePageState(payload = {}, append = false) {
  if (payload.facets?.stages && payload.facets?.tags && payload.facets?.stances) {
    knowledgeFacets = payload.facets;
  }
  const received = Array.isArray(payload.claims) ? payload.claims.length : 0;
  knowledgePageState = {
    total: normalizeCount(payload.total) ?? (append ? Math.max(knowledgePageState.total, knowledgeClaims.length) : received),
    limit: normalizeCount(payload.limit) ?? KNOWLEDGE_PAGE_SIZE,
    offset: (normalizeCount(payload.offset) ?? 0) + received,
    hasMore: Boolean(payload.has_more),
    loading: false,
    error: "",
  };
}

function appendUniqueById(existing, incoming) {
  const seen = new Set(existing.map((item) => item.id));
  return [...existing, ...incoming.filter((item) => item.id && !seen.has(item.id))];
}

function applyApiCollections({ nextSources, nextVideos, nextKnowledgeClaims }) {
  if (Array.isArray(nextSources)) {
    sources = nextSources;
  }
  if (Array.isArray(nextVideos)) {
    videos = sortVideosByPublishTime(nextVideos);
  }
  if (Array.isArray(nextKnowledgeClaims)) {
    knowledgeClaims = nextKnowledgeClaims;
  }
  if (activeSourceFilter && !sources.some((source) => source.id === activeSourceFilter.id)) {
    activeSourceFilter = null;
  }
  if (!selectedVideoId || (activeView !== "detail" && !videos.some((video) => video.id === selectedVideoId))) {
    selectedVideoId = videos[0]?.id || null;
  }
}

function applyBootstrapPayload(payload, { preserveVideoList = false } = {}) {
  applyApiHealth(payload.health || {});
  const knowledgePayload = payload.knowledge || {};
  if (knowledgePayload.facets) knowledgeFacets = knowledgePayload.facets;
  apiStats = normalizeApiStats(payload.stats || {});
  const collections = {
    nextSources: payload.sources || [],
  };
  if (!preserveVideoList) {
    collections.nextVideos = (payload.videos || []).map(normalizeApiVideo);
    updateVideoPageState({ ...(payload.videos_page || {}), videos: payload.videos || [], facets: payload.video_facets });
  } else {
    videoFacets = payload.video_facets || videoFacets;
  }
  if (!knowledgePayload.deferred) {
    collections.nextKnowledgeClaims = (knowledgePayload.claims || []).map(normalizeKnowledgeClaim);
    updateKnowledgePageState(knowledgePayload);
  }
  applyApiCollections(collections);
}

function buildQueryString(params) {
  const query = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "" && value !== "全部") {
      query.set(key, value);
    }
  });
  const text = query.toString();
  return text ? `?${text}` : "";
}

function getKnowledgeApiParams(offset = 0) {
  const query = document.querySelector("#knowledge-query")?.value.trim() || "";
  const params = {
    limit: KNOWLEDGE_PAGE_SIZE,
    offset,
    q: query,
  };
  if (activeKnowledgeCategory.type === "tag") {
    params.tag = activeKnowledgeCategory.value;
  } else if (activeKnowledgeCategory.type === "stance") {
    params.stance = activeKnowledgeCategory.value;
  } else if (activeKnowledgeCategory.type === "authorStance") {
    params.author_stance = activeKnowledgeCategory.value;
  } else if (activeKnowledgeCategory.type === "contentType") {
    params.content_type = activeKnowledgeCategory.value;
  } else if (activeKnowledgeCategory.type === "stage") {
    params.stage = activeKnowledgeCategory.value;
  } else if (activeKnowledgeCategory.type === "stageGroup" && activeKnowledgeCategory.stages?.length) {
    params.stages = activeKnowledgeCategory.stages.join(",");
  }
  return params;
}

function getVideoApiParams(offset = 0) {
  return {
    limit: VIDEO_PAGE_SIZE,
    offset,
    source_id: activeSourceFilter?.id || "",
    platform: activeVideoPlatform,
    creator: activeVideoCreator,
  };
}

function getProgressApiParams(offset = 0) {
  return {
    limit: VIDEO_PAGE_SIZE,
    offset,
    state: activeProgressFilter,
  };
}

function loadKnowledgePage({ append = false, preserveLoaded = false, minimumCount = 0 } = {}) {
  const requestId = ++knowledgeLoadRequestId;
  const offset = append ? knowledgePageState.offset : 0;
  const targetCount = preserveLoaded ? Math.max(KNOWLEDGE_PAGE_SIZE, minimumCount, knowledgeClaims.length) : 0;
  if (!append && !preserveLoaded) knowledgeClaims = [];
  knowledgePageState = { ...knowledgePageState, loading: true, error: "" };
  renderKnowledge();
  const requestPage = (pageOffset) => fetchApiJson(`/knowledge${buildQueryString(getKnowledgeApiParams(pageOffset))}`);
  const firstPagePromise = requestPage(offset);
  const loadedRangePromise = preserveLoaded && !append
    ? firstPagePromise.then(async (firstPage) => {
        const pages = [firstPage];
        let nextOffset = KNOWLEDGE_PAGE_SIZE;
        while (requestId === knowledgeLoadRequestId && nextOffset < targetCount && nextOffset < (firstPage.total || 0)) {
          const next = await requestPage(nextOffset);
          pages.push(next);
          const received = (next.claims || []).length;
          if (!received || !next.has_more) break;
          nextOffset += received;
        }
        return pages;
      })
    : null;
  return (loadedRangePromise || firstPagePromise.then((payload) => [payload]))
    .then((pages) => {
      const payload = pages[0];
      if (requestId !== knowledgeLoadRequestId) return;
      const nextClaims = pages.length > 1
        ? appendUniqueById((pages[0].claims || []).map(normalizeKnowledgeClaim),
            pages.slice(1).flatMap((page) => page.claims || []).map(normalizeKnowledgeClaim))
        : (payload.claims || []).map(normalizeKnowledgeClaim);
      knowledgeClaims = append ? appendUniqueById(knowledgeClaims, nextClaims) : nextClaims;
      if (preserveLoaded) {
        const facetPage = pages[pages.length - 1] || payload;
        updateKnowledgePageState({
          ...facetPage,
          total: payload.total,
          offset: 0,
          has_more: Boolean(facetPage.has_more),
        }, append);
        if (pages.length > 1) {
          knowledgePageState.offset = knowledgeClaims.length;
        }
      } else {
        updateKnowledgePageState(payload, append);
      }
      apiStats = {
        ...apiStats,
        claimCount: normalizeCount(payload.facets?.total) ?? apiStats.claimCount,
      };
      renderOverview();
      renderDetail();
      renderKnowledgeCategories();
      renderKnowledge();
      writeApiCache();
    })
    .catch((error) => {
      if (requestId !== knowledgeLoadRequestId) return;
      knowledgePageState = { ...knowledgePageState, loading: false, error: error.message };
      renderKnowledge();
      console.info("Knowledge page load failed:", error.message);
    });
}

function loadVideoPage({ append = false, preserveLoaded = false } = {}) {
  if (append && videoPageState.loading) return Promise.resolve();
  const requestId = ++videoLoadRequestId;
  const offset = append ? videoPageState.offset : 0;
  const params = getVideoApiParams(offset);
  const retainedCount = preserveLoaded ? Math.max(VIDEO_PAGE_SIZE, videoPageState.offset, videos.length) : VIDEO_PAGE_SIZE;
  if (!append && !preserveLoaded) videos = [];
  videoPageState = { ...videoPageState, loading: true, error: "" };
  renderVideos();
  const fetchPage = async () => {
    if (!preserveLoaded) return fetchApiJson(`/videos${buildQueryString(params)}`);
    // Refill the already loaded range without collapsing a scrolled list to page one.
    let collected = [];
    let payload;
    do {
      payload = await fetchApiJson(`/videos${buildQueryString({ ...params, offset: collected.length, limit: Math.min(100, retainedCount - collected.length) })}`);
      if (requestId !== videoLoadRequestId) return payload;
      collected.push(...(payload.videos || []));
    } while (payload.has_more && payload.videos?.length && collected.length < retainedCount);
    return { ...payload, videos: collected, offset: 0 };
  };
  return fetchPage()
    .then((payload) => {
      if (requestId !== videoLoadRequestId) return;
      const nextVideos = (payload.videos || []).map(normalizeApiVideo);
      videos = sortVideosByPublishTime(append ? appendUniqueById(videos, nextVideos) : nextVideos);
      updateVideoPageState(payload, append);
      if (!selectedVideoId || (activeView !== "detail" && !videos.some((video) => video.id === selectedVideoId))) {
        selectedVideoId = videos[0]?.id || null;
      }
      renderAll();
      writeApiCache();
    })
    .catch((error) => {
      if (requestId !== videoLoadRequestId) return;
      videoPageState = { ...videoPageState, loading: false, error: error.message };
      renderVideos();
      console.info("Video page load failed:", error.message);
    });
}

function loadProgressPage({ append = false } = {}) {
  if (!adminSession.authenticated) return Promise.resolve();
  const offset = append ? progressPageState.offset : 0;
  progressPageState = { ...progressPageState, loading: true, error: "" };
  renderProgress();
  return fetchApiJson(`/progress-videos${buildQueryString(getProgressApiParams(offset))}`)
    .then((payload) => {
      const nextVideos = (payload.videos || []).map(normalizeApiVideo);
      progressVideos = sortVideosByPublishTime(append ? appendUniqueById(progressVideos, nextVideos) : nextVideos);
      updateProgressPageState(payload, append);
      renderProgress();
      writeApiCache();
    })
    .catch((error) => {
      progressPageState = { ...progressPageState, loading: false, error: error.message };
      renderProgress();
      console.info("Progress page load failed:", error.message);
    });
}

function loadProgressSummary() {
  if (!adminSession.authenticated) return Promise.resolve();
  return fetchApiJson("/progress-summary")
    .then((payload) => {
      progressSummary = payload.counts || null;
      renderProgress();
      writeApiCache();
    })
    .catch((error) => {
      console.info("Progress summary load failed:", error.message);
    });
}

async function fetchApiJson(path) {
  if (window.DECOR_PUBLIC_LIBRARY) return window.DECOR_PUBLIC_LIBRARY.get(path);
  const response = await fetch(`${API_BASE}${path}`, { credentials: "include" });
  if (!response.ok) {
    const error = new Error(`${path.replace(/^\//, "")} ${response.status}`);
    error.status = response.status;
    throw error;
  }
  return response.json();
}

async function loadApiData(options = {}) {
  const attempt = options.attempt || 1;
  const requestId = ++apiLoadRequestId;
  apiLoadState = { status: "loading", error: "", attempts: attempt };
  const cachedSnapshot = attempt === 1 ? readApiCache() : null;
  if (cachedSnapshot && !videos.length) {
    applyApiSnapshot(cachedSnapshot);
    renderAll();
  } else if (!videos.length) {
    renderVideos();
  }

  try {
    const bootstrapPayload = await fetchApiJson("/bootstrap");
    if (requestId !== apiLoadRequestId) return;
    const preserveVideoList = Boolean(activeSourceFilter || activeVideoPlatform !== "全部" || activeVideoCreator !== "全部" || videos.length > VIDEO_PAGE_SIZE);
    applyBootstrapPayload(bootstrapPayload, { preserveVideoList });
    if (preserveVideoList) await loadVideoPage({ preserveLoaded: true });
    apiLoadState = { status: "ready", error: "", attempts: attempt };
    renderAll();
    if (activeView === "sources") loadSourcePerformance();
    writeApiCache();
    if (bootstrapPayload.knowledge?.deferred) {
      loadKnowledgePage();
    }
    loadProgressSummary();
    loadProgressPage();
    if (activeView === "detail" && selectedVideoId) {
      loadSelectedVideoDetail();
    }
    return;
  } catch (error) {
    console.info("Bootstrap data load failed, falling back to split endpoints:", error.message);
  }

  const healthPromise = fetchApiJson("/health");
  const sourcesPromise = fetchApiJson("/sources").then((payload) => payload.sources || []);
  const videosPromise = fetchApiJson(`/videos${buildQueryString({ limit: VIDEO_PAGE_SIZE, offset: 0 })}`);
  const knowledgePromise = fetchApiJson(`/knowledge${buildQueryString({ limit: KNOWLEDGE_PAGE_SIZE, offset: 0 })}`)
    .catch((error) => {
      console.info("Knowledge data load failed:", error.message);
      return null;
    });

  try {
    const [healthResult, sourcesResult, videosResult] = await Promise.allSettled([healthPromise, sourcesPromise, videosPromise]);
    if (requestId !== apiLoadRequestId) return;

    if (healthResult.status === "fulfilled") {
      applyApiHealth(healthResult.value);
    } else {
      apiHealthState = { ok: false, dbAvailable: true, dbMessage: healthResult.reason.message };
      console.info("Health check failed:", healthResult.reason.message);
    }

    if (sourcesResult.status === "fulfilled") {
      sources = sourcesResult.value;
    } else {
      console.info("Sources data load failed:", sourcesResult.reason.message);
    }

    if (videosResult.status === "fulfilled") {
      videos = sortVideosByPublishTime((videosResult.value.videos || []).map(normalizeApiVideo));
      updateVideoPageState(videosResult.value);
    } else if (!videos.length) {
      throw videosResult.reason;
    } else {
      console.info("Videos data load failed, keeping cached data:", videosResult.reason.message);
    }

    apiLoadState = { status: "ready", error: "", attempts: attempt };
    if (activeSourceFilter && !sources.some((source) => source.id === activeSourceFilter.id)) {
      activeSourceFilter = null;
    }
    if (!selectedVideoId || !videos.some((video) => video.id === selectedVideoId)) {
      selectedVideoId = videos[0]?.id || null;
    }
    apiStats = {
      ...apiStats,
      sourceCount: sources.length,
      videoCount: normalizeCount(videosResult.value.total) ?? videos.length,
      transcriptCount: videos.filter(hasVideoTranscript).length,
    };
    renderAll();
    if (activeView === "sources") loadSourcePerformance();
    writeApiCache();
    loadProgressSummary();
    loadProgressPage();

    knowledgePromise.then((payload) => {
      if (requestId !== apiLoadRequestId || !payload) return;
      knowledgeClaims = (payload.claims || []).map(normalizeKnowledgeClaim);
      updateKnowledgePageState(payload);
      apiStats = {
        ...apiStats,
        claimCount: normalizeCount(payload.total) ?? knowledgeClaims.length,
      };
      renderOverview();
      renderDetail();
      renderKnowledgeCategories();
      renderKnowledge();
      writeApiCache();
    });
  } catch (error) {
    console.info("API data load failed:", error.message);
    apiLoadState = { status: "error", error: error.message, attempts: attempt };
    if (!videos.length) {
      videos = [];
      renderAll();
    } else {
      renderVideos();
    }
    if (attempt < 3) {
      window.setTimeout(() => {
        loadApiData({ attempt: attempt + 1 });
      }, attempt * 1500);
    }
  }
}

async function loadVideoDetail(videoId) {
  const version = videoDetailVersions.get(videoId) || 0;
  let detail;
  try {
    detail = await fetchApiJson(`/videos/${encodeURIComponent(videoId)}`);
  } catch (error) {
    if (error.status !== 404) throw error;
    detail = await fetchApiJson(`/knowledge/sources/${encodeURIComponent(videoId)}`);
  }
  if (version !== (videoDetailVersions.get(videoId) || 0)) return null;
  const detailedVideo = normalizeApiVideo({
    ...detail.video,
    claim_count: detail.claims.length,
    claims: detail.claims,
  });
  if (detailedVideo.sourceReadOnly) {
    detailedVideos.delete(videoId);
    retainedSourceDetails.set(videoId, detailedVideo);
    return detailedVideo;
  }
  retainedSourceDetails.delete(videoId);
  detailedVideos.set(videoId, detailedVideo);
  // A source can be outside the loaded pages; reading it must not alter list pagination.
  const updateExisting = (video) => video.id === videoId ? { ...video, ...detailedVideo } : video;
  videos = videos.map(updateExisting);
  progressVideos = progressVideos.map(updateExisting);
  writeApiCache();
  return detailedVideo;
}

function findDetailVideo(videoId) {
  if (isDeletedVideoDetail() && videoId === selectedVideoId) return adminSession.authenticated ? deletedVideoDetails.get(videoId) || null : null;
  if (!videoId) return videos[0] || progressVideos[0] || null;
  return detailedVideos.get(videoId) || retainedSourceDetails.get(videoId) || videos.find((item) => item.id === videoId) || progressVideos.find((item) => item.id === videoId) || null;
}

function setSourceMessage(message, type = "") {
  const sourceMessage = document.querySelector("#source-message");
  if (!sourceMessage) return;
  sourceMessage.textContent = message;
  sourceMessage.dataset.type = type;
}

function setIngestMessage(message, type = "") {
  ingestMessage.textContent = message;
  ingestMessage.dataset.type = type;
}

function setIngestOpen(isOpen) {
  if (ingestSubmitting) return;
  ingestPanel.hidden = !isOpen;
  openIngestButton?.setAttribute("aria-expanded", String(isOpen));
  if (isOpen) {
    setView("sources");
    setIngestMessage("");
    ingestForm.querySelector("[name='batch_profile_url']").focus();
  } else {
    openIngestButton?.focus();
  }
}

async function postJson(url, payload) {
  if (window.DECOR_PUBLIC_LIBRARY) throw new Error("公开预览仅支持浏览，不支持修改或删除。");
  const response = await fetch(url, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    if (response.status === 401 && data.error === "admin login required") {
      adminSession = { ...adminSession, authenticated: false };
      renderAdminSession();
      throw new Error("管理员登录已失效，请重新登录后操作。");
    }
    throw new Error(data.error || data.message || `${response.status}`);
  }
  return data;
}

async function getJson(url) {
  if (window.DECOR_PUBLIC_LIBRARY) return window.DECOR_PUBLIC_LIBRARY.get(url);
  const response = await fetch(url, { credentials: "include" });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(data.error || data.message || `${response.status}`);
  }
  return data;
}

async function deleteJson(url) {
  if (window.DECOR_PUBLIC_LIBRARY) throw new Error("公开预览仅支持浏览，不支持修改或删除。");
  const response = await fetch(url, {
    method: "DELETE",
    credentials: "include",
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(data.error || data.message || `${response.status}`);
  }
  return data;
}

function formPayload(form) {
  const formData = new FormData(form);
  return Object.fromEntries(
    [...formData.entries()].map(([key, value]) => [key, typeof value === "string" ? value.trim() : value]),
  );
}

function extractUrl(text) {
  return (text.match(/https?:\/\/[^\s，。！？、)）]+/) || [""])[0].replace(/[.,;，。；]+$/, "");
}

function parseBatchVideoLinks(text) {
  return (text || "")
    .split(/\n+/)
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line, index) => {
      const sourceUrl = extractUrl(line) || line;
      const title = line.replace(sourceUrl, "").replace(/^[\s\-:：|]+|[\s\-:：|]+$/g, "");
      return {
        source_url: sourceUrl,
        title: title || `作品 ${index + 1}`,
      };
    });
}

async function saveVideoFromForm(mode) {
  requireAdminAction();
  const payload = formPayload(ingestForm);
  if (mode === "batch") {
    await batchCollectVideos(payload);
    return;
  }
  if (mode === "quick" || mode === "quick-extract") {
    await quickIngestVideo(payload, mode === "quick-extract");
    return;
  }

  const transcriptText = payload.transcript_text;
  if (!transcriptText) {
    throw new Error("请在手动兜底录入中填写原始文案");
  }
  const videoPayload = {
    platform: payload.platform,
    creator: payload.creator,
    title: payload.title,
    source_url: payload.source_url,
    share_url: payload.share_url || payload.source_url,
    share_text: payload.share_text,
    published_at: payload.published_at,
  };

  setIngestMessage(mode === "extract" ? "正在保存文案并调用模型提取..." : "正在保存文案...");
  const saved = await postJson(`${API_BASE}/videos`, videoPayload);
  const videoId = saved.video.id;

  await postJson(`${API_BASE}/videos/${videoId}/share`, {
    share_url: videoPayload.share_url,
    share_text: videoPayload.share_text,
  });
  await postJson(`${API_BASE}/videos/${videoId}/transcript`, {
    transcript_text: transcriptText,
    transcript_source: "TranscriptGenerate/manual",
  });

  if (mode === "extract") {
    const extracted = await postJson(`${API_BASE}/videos/${videoId}/extract`, {});
    if (!["completed", "filtered"].includes(extracted.status)) {
      throw new Error(extracted.status || "extract_failed");
    }
  }

  await loadApiData();
  selectedVideoId = videoId;
  renderAll();
  renderDetail();
  setView("detail");
  setIngestOpen(false);
  ingestForm.reset();
  setIngestMessage("");
}

async function quickIngestVideo(payload, shouldExtract) {
  requireAdminAction();
  const shareInput = payload.share_text || payload.share_url || payload.source_url;
  const transcriptText = payload.transcript_text || "";
  if (!shareInput) {
    throw new Error("请填写来源视频链接或分享链接");
  }

  setIngestMessage(shouldExtract ? "正在保存文案并提取观点..." : "正在保存原始文案...");
  const result = await postJson(`${API_BASE}/videos/quick-ingest`, {
    share_text: shareInput,
    share_url: payload.share_url || payload.source_url || extractUrl(shareInput),
    platform: payload.platform,
    creator: payload.creator,
    title: payload.title,
    published_at: payload.published_at,
    transcript_text: transcriptText,
    transcript_source: transcriptText ? "AnyToCopy/manual" : undefined,
    extract: shouldExtract,
  });
  if (shouldExtract && !["completed", "filtered", "skipped_existing_extraction", "skipped_advertising"].includes(result.extraction?.status)) {
    throw new Error(result.extraction?.status || "extract_failed");
  }

  await loadApiData();
  selectedVideoId = result.video.id;
  renderAll();
  renderDetail();
  setView("detail");
  setIngestOpen(false);
  ingestForm.reset();
  setIngestMessage("");
}

function removeVideoFromState(videoId, deleteClaims = true) {
  videoDetailVersions.set(videoId, (videoDetailVersions.get(videoId) || 0) + 1);
  detailedVideos.delete(videoId);
  retainedSourceDetails.delete(videoId);
  if (videos.some((video) => video.id === videoId)) {
    videoPageState.total = Math.max(0, videoPageState.total - 1);
    videoPageState.offset = Math.max(0, videoPageState.offset - 1);
  }
  if (progressVideos.some((video) => video.id === videoId)) {
    progressPageState.total = Math.max(0, progressPageState.total - 1);
    progressPageState.offset = Math.max(0, progressPageState.offset - 1);
  }
  videos = videos.filter((video) => video.id !== videoId);
  progressVideos = progressVideos.filter((video) => video.id !== videoId);
  if (deleteClaims) knowledgeClaims = knowledgeClaims.filter((claim) => claim.videoId !== videoId);
  if (selectedVideoId === videoId) {
    selectedVideoId = videos[0]?.id || progressVideos[0]?.id || null;
  }
}

function removeClaimFromState(claimId, videoId) {
  knowledgeClaims = knowledgeClaims.filter((claim) => claim.id !== claimId);
  const detail = detailedVideos.get(videoId);
  if (detail) {
    detailedVideos.set(videoId, { ...detail, claims: detail.claims.filter((claim) => claim.id !== claimId),
      claimCount: Math.max(0, detail.claimCount - 1) });
  }
  videos = videos.map((video) => {
    if (video.id !== videoId) return video;
    const claims = video.claims.filter((claim) => claim.id !== claimId);
    return { ...video, claims, claimCount: Math.max(0, Number(video.claimCount || 0) - 1) };
  });
  progressVideos = progressVideos.map((video) => {
    if (video.id !== videoId) return video;
    const claims = video.claims.filter((claim) => claim.id !== claimId);
    return { ...video, claims, claimCount: Math.max(0, Number(video.claimCount || 0) - 1) };
  });
}

function confirmVideoDeletion(video, { permanent = false } = {}) {
  const dialog = document.querySelector("#video-delete-dialog");
  if (dialog.open) return Promise.resolve(null);
  document.querySelector("#video-delete-name").textContent = video.title || video.id;
  const deleteClaims = document.querySelector("#video-delete-claims");
  document.querySelector("#video-delete-title").textContent = permanent ? "永久删除这个视频？" : "将视频移入回收站？";
  document.querySelector("#video-delete-desc").textContent = permanent ? "将清除视频文案、提取记录及全部关联知识卡，无法恢复。" : "可在回收站恢复。";
  document.querySelector(".video-delete-option").hidden = permanent;
  document.querySelector(".video-delete-confirm").textContent = permanent ? "永久删除" : "移入回收站";
  deleteClaims.checked = true;
  dialog.returnValue = "cancel";
  return new Promise((resolve) => {
    dialog.addEventListener("close", () => {
      resolve(dialog.returnValue === "confirm" ? { deleteClaims: deleteClaims.checked } : null);
    }, { once: true });
    dialog.showModal();
  });
}

const deletingVideoIds = new Set();
let libraryMetadataRequestId = 0;

async function refreshLibraryMetadata() {
  const requestId = ++libraryMetadataRequestId;
  // Refresh counts without applying bootstrap's first page over the user's loaded range.
  const payload = await fetchApiJson("/bootstrap");
  if (requestId !== libraryMetadataRequestId) return;
  sources = payload.sources || sources;
  apiStats = normalizeApiStats(payload.stats || {});
  videoFacets = payload.video_facets || videoFacets;
  knowledgeFacets = payload.knowledge?.facets || knowledgeFacets;
  renderIfActive("overview", "sources", "videos");
  writeApiCache();
}

async function deleteVideo(videoId) {
  if (deletingVideoIds.has(videoId)) return;
  if (!adminSession.authenticated) {
    await loginAdmin();
    if (!adminSession.authenticated) return;
  }
  const video = findDetailVideo(videoId);
  if (!video) return;
  deletingVideoIds.add(videoId);
  try {
    const confirmation = await confirmVideoDeletion(video);
    if (!confirmation) return;
    const scrollPosition = { left: window.scrollX, top: window.scrollY };
    const deletionView = activeView;
    const deletionEntryKey = navigationEntryKey;
    const wasDetail = deletionView === "detail" && selectedVideoId === videoId;
    const returnPosition = history.state?.returnView === "videos" ? navigationPositions.get(history.state.returnEntryKey) : null;
    await deleteJson(`${API_BASE}/videos/${videoId}?delete_claims=${confirmation.deleteClaims}`);
    removeVideoFromState(videoId, confirmation.deleteClaims);
    await Promise.allSettled([loadProgressSummary(), loadKnowledgePage(), loadVideoPage({ preserveLoaded: true }), refreshLibraryMetadata()]);
    renderAll();
    if (wasDetail && activeView === "detail" && navigationEntryKey === deletionEntryKey) {
      setView("videos", { replaceHistory: true });
      restoreNavigationPosition(returnPosition);
      return;
    }
    if (activeView === deletionView) {
      window.scrollTo({ ...scrollPosition, behavior: "instant" });
    }
  } finally {
    deletingVideoIds.delete(videoId);
  }
}

const purgingVideoIds = new Set();

async function purgeVideo(videoId) {
  requireAdminAction();
  if (purgingVideoIds.has(videoId)) return;
  const video = deletedItems.videos.find(item => item.id === videoId);
  if (!video) return;
  purgingVideoIds.add(videoId);
  try {
    if (!await confirmVideoDeletion(video, { permanent: true })) return;
    const position = { left: window.scrollX, top: window.scrollY };
    await deleteJson(`${API_BASE}/admin/deleted/videos/${encodeURIComponent(videoId)}`);
    removeVideoFromState(videoId, true);
    deletedVideoDetails.delete(videoId);
    deletedItems.videos = deletedItems.videos.filter(item => item.id !== videoId);
    deletedItems.claims = deletedItems.claims.filter(item => item.video_id !== videoId);
    await Promise.allSettled([loadDeletedItems({ preserveLoaded: true }), loadKnowledgePage(), refreshLibraryMetadata(), loadProgressSummary()]);
    renderAll();
    if (activeView === "deleted") window.scrollTo({ ...position, behavior: "instant" });
  } finally {
    purgingVideoIds.delete(videoId);
  }
}

async function deleteClaim(claimId, videoId) {
  if (!adminSession.authenticated) {
    await loginAdmin();
    if (!adminSession.authenticated) return;
  }
  if (!confirm("确定删除这条观点吗？")) return;
  const scrollPosition = { left: window.scrollX, top: window.scrollY };
  const deletionView = activeView;
  const deletionEntryKey = navigationEntryKey;
  const knownLoadedCount = knowledgeClaims.length;
  const result = await deleteJson(`${API_BASE}/claims/${claimId}`);
  removeClaimFromState(claimId, result.video_id || videoId);
  await Promise.allSettled([loadProgressSummary(), loadKnowledgePage({ preserveLoaded: true,
    minimumCount: knownLoadedCount })]);
  if (deletionView === "detail" && selectedVideoId) {
    await loadVideoDetail(selectedVideoId).catch(() => {});
  }
  renderAll();
  if (activeView === deletionView && navigationEntryKey === deletionEntryKey) {
    window.scrollTo({ ...scrollPosition, behavior: "instant" });
  }
}

async function batchCollectVideos(payload) {
  requireAdminAction();
  if (!payload.batch_profile_url) {
    throw new Error("请填写主页链接");
  }
  const limit = Number(payload.batch_limit);
  if (!Number.isInteger(limit) || limit < 1 || limit > 50) {
    throw new Error("采集数量需为 1 到 50 的整数");
  }
  const profileUrl = payload.batch_profile_url;
  const existingSource = sources.find((source) => source.profile_url === profileUrl || source.profile_url?.split("?")[0] === profileUrl.split("?")[0]);

  setIngestMessage("正在更新主页最新作品...");
  let sourceId = existingSource?.id;
  if (!sourceId) {
    const created = await postJson(`${API_BASE}/sources`, {
      platform: "抖音",
      name: "待识别博主",
      profile_url: profileUrl,
      priority: "P1",
      status: "active",
      notes: "通过主页链接创建，待采集后补充博主信息。",
    });
    sourceId = created.id;
  }
  const result = await postJson(`${API_BASE}/sources/${sourceId}/update`, { limit });

  await loadApiData();
  if (result.videos?.length) {
    selectedVideoId = result.videos[0].id;
  }
  renderAll();
  setView("sources");
  ingestPanel.hidden = true;
  openIngestButton?.setAttribute("aria-expanded", "false");
  ingestForm.reset();
  setSourceMessage(
    result.message || (result.stats
      ? `更新完成：新增 ${result.stats.created} 条，重复 ${result.stats.duplicate} 条。`
      : "来源已保存，作品采集完成。"),
    "ok",
  );
}

async function updateSource(sourceId) {
  requireAdminAction();
  setSourceMessage("正在请求更新来源...");
  const result = await postJson(`${API_BASE}/sources/${sourceId}/update`, { limit: 5 });
  await loadApiData();
  renderAll();
  setView("sources");
  setSourceMessage(
    result.message || (result.stats
      ? `更新完成：新增 ${result.stats.created} 条，重复 ${result.stats.duplicate} 条。`
      : result.status),
    "ok",
  );
}

async function updateAllSources() {
  requireAdminAction();
  setSourceMessage("正在串行更新所有启用的来源，请等待采集完成...");
  const result = await postJson(`${API_BASE}/sources/update-all`, { limit: 5 });
  let refreshError = "";
  try {
    await loadApiData();
  } catch (error) {
    refreshError = `列表刷新失败：${error.message}，请刷新页面查看已保存结果。`;
  }
  renderAll();
  setView("sources");
  const labels = { completed: "更新完成", partial: "部分更新完成", failed: "更新失败", skipped: "未执行更新" };
  const types = { completed: "ok", partial: "warn", failed: "error", skipped: "warn" };
  const stats = result.stats;
  const summary = result.summary;
  let message = labels[result.status] || "更新结果异常";
  if (summary) {
    message += `：成功 ${summary.completed} 个来源，失败 ${summary.failed} 个，跳过 ${summary.skipped} 个`;
  }
  if (stats) {
    message += `；新增 ${stats.created} 条，重复 ${stats.duplicate} 条。`;
  }
  if (result.message) message = result.message;
  const details = (result.sources || [])
    .filter((source) => source.status !== "completed")
    .map((source) => `${source.name || source.source_id}：${source.message || source.error || source.status}`);
  if (details.length) message += ` ${details.join("；")}`;
  if (refreshError) message += ` ${refreshError}`;
  const type = types[result.status] || "error";
  setSourceMessage(message, refreshError && type === "ok" ? "warn" : type);
}

function refreshDouyinLoginStatus() {
  if (douyinLoginRequest) return douyinLoginRequest;
  const requestId = ++douyinLoginRequestId;
  douyinLoginChecking = true;
  renderSources();
  douyinLoginRequest = getJson(`${API_BASE}/douyin/login-status`)
    .then((status) => {
      if (requestId !== douyinLoginRequestId) return douyinLoginStatus;
      douyinLoginStatus = status;
      if (!status.running && douyinLoginTimer) {
        clearInterval(douyinLoginTimer);
        douyinLoginTimer = null;
      }
      return status;
    })
    .catch((error) => {
      if (requestId === douyinLoginRequestId) {
        douyinLoginStatus = { status: "unknown", message: error.message, logged_in: null, running: false };
      }
      throw error;
    })
    .finally(() => {
      douyinLoginChecking = false;
      douyinLoginRequest = null;
      renderSources();
    });
  return douyinLoginRequest;
}

async function startDouyinLogin(profileUrl) {
  requireAdminAction();
  ++douyinLoginRequestId;
  setSourceMessage("正在打开抖音登录窗口...");
  const status = await postJson(`${API_BASE}/douyin/login/start`, {
    profile_url: profileUrl || "https://www.douyin.com/",
    wait_seconds: 240,
  });
  douyinLoginStatus = status;
  renderSources();
  setSourceMessage(status.message || "已打开抖音登录窗口，请完成登录。", "warn");
  if (douyinLoginTimer) clearInterval(douyinLoginTimer);
  douyinLoginTimer = setInterval(() => {
    refreshDouyinLoginStatus().catch((error) => setSourceMessage(`登录态检查失败：${error.message}`, "error"));
  }, 3000);
}

function setQueueMessage(message, type = "") {
  queueMessage.textContent = message;
  queueMessage.dataset.type = type;
}

function setProgressMessage(message, type = "") {
  if (!progressMessage) return;
  progressMessage.textContent = message;
  progressMessage.dataset.type = type;
}

function setProgressRunButtonState(state, label) {
  if (!progressProcessPendingButton) return;
  const labelEl = progressProcessPendingButton.querySelector("[data-run-label]");
  progressProcessPendingButton.dataset.state = state;
  setAdminActionBusy(progressProcessPendingButton, state === "starting");
  if (labelEl) labelEl.textContent = label;
}

function formatLogLine(line) {
  return String(line || "")
    .replace(/\s+(TranscriptGenerate raw excerpt:)/g, "\n  $1")
    .replace(/\s+(response=\{)/g, "\n  $1")
    .replace(/\s+(code=)/g, "\n  $1")
    .replace(/\s+(msg=)/g, "\n  $1")
    .replace(/\s+(status=)/g, "\n  $1")
    .replace(/\s+(transcript_[a-z_]+:)/g, "\n  $1")
    .replace(/\s+(best_candidate=)/g, "\n  $1")
    .replace(/\s+(candidates=)/g, "\n  $1")
    .replace(/\s+(selected=)/g, "\n  $1")
    .replace(/\s+(\$\.[\w.[\]]+=)/g, "\n  $1")
    .replace(/,\s+(\$\.[\w.[\]]+=)/g, ",\n  $1")
    .replace(/\s+(\{'.+'\})$/g, "\n  $1");
}

function formatQueueLogs(logs) {
  const lines = Array.isArray(logs) ? logs : [];
  return lines.length ? lines.map(formatLogLine).join("\n") : "[--:--:--] 等待自动队列启动...";
}

function isLogScrolledNearBottom(element) {
  if (!element) return true;
  const distance = element.scrollHeight - element.scrollTop - element.clientHeight;
  return distance < 48;
}

function getQueueLogKey(element) {
  const rowPanel = element?.closest?.("[data-row-log-video-id]");
  return rowPanel ? `row:${rowPanel.dataset.rowLogVideoId}` : "global";
}

function updateQueueLogFollowButton(key, panel) {
  const button = panel?.querySelector?.("[data-log-follow-bottom]");
  if (!button) return;
  const isFollowing = queueLogFollowState[key] !== false;
  button.hidden = isFollowing;
  button.textContent = "跳到底部";
}

function attachQueueLogScrollState(element) {
  if (!element || element.dataset.scrollStateReady === "true") return;
  element.dataset.scrollStateReady = "true";
  const key = getQueueLogKey(element);
  queueLogFollowState[key] = queueLogFollowState[key] !== false;
  element.addEventListener("scroll", () => {
    queueLogFollowState[key] = isLogScrolledNearBottom(element);
    updateQueueLogFollowButton(key, element.closest(".queue-log-panel"));
  });
  updateQueueLogFollowButton(key, element.closest(".queue-log-panel"));
}

function setLogTextPreservingScroll(element, text) {
  if (!element) return;
  attachQueueLogScrollState(element);
  const key = getQueueLogKey(element);
  const shouldFollow = queueLogFollowState[key] !== false;
  const previousScrollTop = element.scrollTop;
  element.textContent = text;
  element.scrollTop = shouldFollow ? element.scrollHeight : previousScrollTop;
  updateQueueLogFollowButton(key, element.closest(".queue-log-panel"));
}

function jumpLogToBottom(panel) {
  const body = panel?.querySelector?.("pre");
  if (!body) return;
  const key = getQueueLogKey(body);
  queueLogFollowState[key] = true;
  body.scrollTop = body.scrollHeight;
  updateQueueLogFollowButton(key, panel);
}

async function locateNextTranscriptVideo() {
  setQueueMessage("正在查找下一条待提取文案视频...");
  const result = await getJson(`${API_BASE}/queue/next`);
  if (!result.next_transcript) {
    setQueueMessage("没有待提取文案视频。", "ok");
    return;
  }
  selectedVideoId = result.next_transcript.id;
  await loadApiData();
  selectedVideoId = result.next_transcript.id;
  renderAll();
  renderDetail();
  setView("detail");
  setQueueMessage(`待提取文案：${result.next_transcript.title}`, "ok");
}

async function extractNextQueuedVideo() {
  requireAdminAction();
  setQueueMessage("正在提取下一条已保存文案...");
  const result = await postJson(`${API_BASE}/queue/extract-next`, {});
  if (result.status === "empty") {
    setQueueMessage("没有已保存文案等待提取。", "ok");
    return result;
  }
  if (!["completed", "filtered", "skipped_existing_extraction", "skipped_advertising"].includes(result.status)) {
    throw new Error(result.status || "extract_failed");
  }
  await loadApiData();
  selectedVideoId = result.video.id;
  renderAll();
  renderDetail();
  setView("detail");
  const skipped = result.status.startsWith("skipped_");
  setQueueMessage(skipped ? result.message || "已跳过自动提取。" : `已提取：${result.video.title}，新增 ${result.claims.length} 条观点。`, "ok");
  return result;
}

async function retryVideoTranscript(videoId) {
  requireAdminAction();
  setProgressMessage("正在重新提取视频文案...");
  const result = await postJson(`${API_BASE}/videos/${videoId}/transcript/retry`, {});
  await loadApiData();
  renderAll();
  setView("progress");
  setProgressMessage(`文案已保存：${result.video.title}`, "ok");
}

async function processPendingQueue(limit = 5) {
  requireAdminAction();
  setProgressMessage(`自动处理中：最多 ${limit} 条，按队列串行执行...`);
  const result = await postJson(`${API_BASE}/queue/process-pending`, {
    limit,
    delay_seconds: 25,
  });
  await loadApiData();
  renderAll();
  setView("progress");
  const failedText = result.failed?.length ? `，失败 ${result.failed.length} 条` : "";
  setProgressMessage(`自动处理完成：成功 ${result.processed?.length || 0} 条${failedText}，剩余 ${result.remaining} 条。`, result.failed?.length ? "warn" : "ok");
}

function renderQueueStatus(status) {
  lastQueueStatus = status;
  const bodyText = formatQueueLogs(status.logs);
  const processed = status.processed?.length || 0;
  const failed = status.failed?.length || 0;
  const metaText = status.job_id
    ? `${status.job_id} / ${status.running ? "运行中" : "已结束"} / 成功 ${processed} / 失败 ${failed} / 剩余 ${status.remaining ?? "-"}`
    : "暂无任务";
  const resultText = getQueueResultText(status);
  if (queueLogPanel && queueLogBody) {
    if (queueLogMode === "row") {
      queueLogPanel.hidden = true;
    } else {
    queueLogPanel.hidden = false;
    queueLogMeta.textContent = metaText;
    setLogTextPreservingScroll(queueLogBody, bodyText);
    }
  }
  const rowPanel = activeProgressLogVideoId ? document.querySelector(`[data-row-log-video-id="${activeProgressLogVideoId}"]`) : null;
  if (!rowPanel) return;
  const rowMeta = rowPanel.querySelector("[data-row-log-meta]");
  const rowTitle = rowPanel.querySelector("[data-row-log-title]");
  const rowBody = rowPanel.querySelector("[data-row-log-body]");
  if (rowTitle) rowTitle.textContent = resultText || "本条重试日志";
  if (rowMeta) rowMeta.textContent = metaText;
  if (rowBody) {
    setLogTextPreservingScroll(rowBody, bodyText);
  }
}

function getQueueResultText(status) {
  if (!status?.job_id) return "";
  if (status.running) return "处理中...";
  const failed = status.failed || [];
  const processed = status.processed || [];
  if (failed.length) {
    const error = failed[0]?.error || "处理失败";
    const shortMatch = error.match(/文案过短，长度\s*(\d+)/);
    if (shortMatch) return `文案过短，已拉取 ${shortMatch[1]} 字，未进入观点提取`;
    return `处理失败：${error}`;
  }
  if (processed.some((item) => item.stage === "skipped_advertising")) return "推广或待确认内容，已跳过自动观点提取";
  if (processed.some((item) => item.stage === "skipped_existing_extraction")) return "文案已尝试提取，已跳过自动重试";
  if (processed.length) return "处理完成";
  return "处理结束，未产生新结果";
}

function getLatestQueueLogForVideo(videoId) {
  const logs = lastQueueStatus?.logs || [];
  for (let index = logs.length - 1; index >= 0; index -= 1) {
    const line = logs[index] || "";
    if (line.includes(videoId)) {
      return line;
    }
  }
  return "";
}

function getLiveProgressStage(video) {
  const logLine = getLatestQueueLogForVideo(video.id);
  const failed = (lastQueueStatus?.failed || []).some((item) => item.video_id === video.id);
  const processed = (lastQueueStatus?.processed || []).some((item) => item.video_id === video.id);
  if (failed || /失败|文案过短/.test(logLine)) {
    return { stage: "failed", line: logLine };
  }
  if (processed || /完成/.test(logLine)) {
    return { stage: "done", line: logLine };
  }
  if (lastQueueStatus?.running && /DeepSeek|观点/.test(logLine)) {
    return { stage: "claims_running", line: logLine };
  }
  if (lastQueueStatus?.running && /拉取文案|文案中/.test(logLine)) {
    return { stage: "transcript_running", line: logLine };
  }
  if (lastQueueStatus?.running && logLine) {
    return { stage: "running", line: logLine };
  }
  return { stage: "", line: "" };
}

function getProgressStageTags(video) {
  const hasLink = Boolean(video.sourceUrl || video.shareUrl);
  const hasTranscript = hasVideoTranscript(video);
  const transcriptLabel = getVideoTranscriptLabel(video);
  const claimCount = video.claimCount || video.claims.length;
  const live = getLiveProgressStage(video);
  const isRunning = ["running", "transcript_running", "claims_running"].includes(live.stage);
  const isFailed = live.stage === "failed" || (!isRunning && getVideoProgressState(video).key === "失败");
  const isFiltered = video.status === "claims_filtered";

  const tags = [
    {
      key: "link",
      title: "链接",
      label: hasLink ? "已获取" : "缺失",
      state: hasLink ? "done" : "failed",
    },
    {
      key: "transcript",
      title: "文案",
      label: transcriptLabel,
      state: hasTranscript ? "done" : "todo",
    },
    {
      key: "claims",
      title: "观点",
      label: claimCount > 0 ? `${claimCount} 条` : video.adReview?.decision === "advertising" ? "推广跳过" : ["uncertain", "error"].includes(video.adReview?.decision) ? "待确认" : isFiltered ? "已过滤" : "待提取",
      state: claimCount > 0 || isFiltered ? "done" : "todo",
    },
  ];

  if (live.stage === "transcript_running") {
    tags[1] = { ...tags[1], label: "提取中", state: "running" };
    if (!hasTranscript) tags[2] = { ...tags[2], label: "等待文案", state: "todo" };
  }
  if (live.stage === "claims_running") {
    tags[1] = { ...tags[1], label: hasTranscript ? transcriptLabel : "已获取", state: "done" };
    tags[2] = { ...tags[2], label: "提取中", state: "running" };
  }
  if (live.stage === "done") {
    tags[0] = { ...tags[0], state: hasLink ? "done" : "failed" };
    tags[1] = { ...tags[1], state: hasTranscript ? "done" : tags[1].state };
    tags[2] = { ...tags[2], state: claimCount > 0 ? "done" : tags[2].state };
  }
  if (isFailed) {
    if (!hasTranscript) {
      tags[1] = { ...tags[1], label: "失败", state: "failed" };
    } else if (claimCount === 0) {
      tags[2] = { ...tags[2], label: "失败", state: "failed" };
    }
  }
  return { tags, live };
}

function renderProgressStageTags(video) {
  const { tags } = getProgressStageTags(video);
  const promotion = getPromotionPresentation(video);
  return tags
    .map((tag) => {
      const canOpenClaims = tag.key === "claims" && tag.state === "done" && (video.claimCount || video.claims.length) > 0;
      const tagName = canOpenClaims ? "button" : "span";
      const actionAttrs = canOpenClaims
        ? ` type="button" data-video-claims-id="${escapeAttr(video.id)}" aria-haspopup="dialog" aria-controls="video-claims-dialog" aria-label="查看 ${escapeAttr(video.title)} 的观点"`
        : "";
      const icon = tag.key === "claims" && tag.state === "todo" && promotion.state !== "neutral" ? promotion.icon
        : tag.state === "running" ? "running" : tag.state === "done" ? "check" : tag.state === "failed" ? "cross" : "clock";
      return `
        <${tagName} class="progress-stage-tag" data-stage="${escapeAttr(tag.key)}" data-state="${escapeAttr(tag.state)}"${actionAttrs}>
          ${videoBadgeSvg(icon)}
          <strong>${escapeHtml(tag.title)}</strong>
          <em>${escapeHtml(tag.label)}</em>
        </${tagName}>
      `;
    })
    .join("");
}

function renderProgressTimeTags(video) {
  return getVideoProgressTimeItems(video)
    .filter((item) => !["未提及", "未记录"].includes(item.value))
    .map(
      (item) => `
        <span class="progress-time-tag" title="${escapeAttr(`${item.label} ${item.value}`)}">
          <span>${item.label === "发布时间" ? "发布" : "更新"}</span>
          <time>${escapeHtml(String(item.value).replace("T", " ").replace(/(\d{2}:\d{2}):\d{2}.*$/, "$1"))}</time>
        </span>
      `,
    )
    .join("");
}

function getProgressPresentation(video, state, live) {
  const running = ["running", "transcript_running", "claims_running"].includes(live.stage);
  if (running) return { tone: "running", label: live.stage === "claims_running" ? "提取观点中" : live.stage === "transcript_running" ? "获取文案中" : "处理中", icon: "running" };
  if (live.stage === "failed" || state.key === "失败" || state.key === "缺链接") return { tone: "failed", label: state.key === "缺链接" ? "缺链接" : "失败", icon: "warning" };
  if (state.key === "待确认" || (state.key === "已完成" && video.adReview?.decision === "advertising")) {
    const promotion = getPromotionPresentation(video);
    return { tone: promotion.state === "promotion" ? "promotion" : "warning", label: promotion.label, icon: promotion.icon, promotionState: promotion.state };
  }
  if (state.key === "已完成") return { tone: "done", label: state.label, icon: "check" };
  return { tone: "pending", label: state.key, icon: "clock" };
}

function getProgressNotice(video) {
  const reason = getVideoReasonLabel(video);
  if (!reason) return null;
  const error = String(video.lastError || "");
  let summary;
  if (video.adReview?.decision === "advertising") summary = "已跳过自动提取";
  else if (["uncertain", "error"].includes(video.adReview?.decision)) summary = video.adReview.decision === "error" ? "推广识别失败" : "推广状态待确认";
  else if (/local_asr_media_unavailable/.test(error)) summary = "视频不可访问，检查登录或权限";
  else if (/deepseek_timeout|timed?\s*out|超时/i.test(error)) summary = "处理超时，可稍后重试";
  else if (/\b503\b|service.unavailable|服务不可用/i.test(error)) summary = "服务暂不可用，可稍后重试";
  else if (/额度|余额|quota|insufficient.balance/i.test(error)) summary = "转写或模型额度不足";
  else if (/文案过短/.test(error)) summary = "文案过短，未提取观点";
  else if (/evidence_/.test(error)) summary = "引句校验未通过";
  else if (/invalid_|quality_check|parse_failed|证据校验|格式校验/.test(error)) summary = "观点校验未通过";
  else if (video.status === "claims_filtered") summary = "没有可收录的观点";
  else summary = reason.replace(/^(处理原因|文案失败)[:：]\s*/, "").replace(/\s+/g, " ");
  if (summary.length > 32) summary = summary.slice(0, 31) + "…";
  return { summary, detail: reason };
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function escapeAttr(value) {
  return escapeHtml(value);
}

function sanitizeUrl(value) {
  const url = String(value ?? "").trim();
  return /^https?:\/\//i.test(url) ? url : "#";
}

function safeUrl(value) {
  return escapeHtml(sanitizeUrl(value));
}

async function copySourceLink(button) {
  const url = sanitizeUrl(button.dataset.copySourceUrl);
  if (url === "#") return;
  const feedback = button.parentElement.querySelector(".copy-link-feedback");
  const setFeedback = (message) => {
    button.title = message || "复制分享链接";
    button.setAttribute("aria-label", message || "复制分享链接");
    if (feedback) feedback.textContent = message;
  };
  button.disabled = true;
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(url);
    } else {
      const previousFocus = document.activeElement;
      const textarea = document.createElement("textarea");
      textarea.value = url;
      textarea.readOnly = true;
      textarea.style.cssText = "position:fixed;left:-9999px;top:0";
      document.body.append(textarea);
      try {
        textarea.select();
        if (!document.execCommand("copy")) throw new Error("clipboard unavailable");
      } finally {
        textarea.remove();
        previousFocus?.focus();
      }
    }
    setFeedback("已复制");
  } catch (error) {
    setFeedback("复制失败，请重试");
  } finally {
    button.disabled = false;
    window.setTimeout(() => {
      setFeedback("");
    }, 2000);
  }
}

function setupAutoLoadMore() {
  if (!("IntersectionObserver" in window)) return;
  if (!autoLoadObserver) {
    autoLoadObserver = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (!entry.isIntersecting) return;
          const target = autoLoadTargets[entry.target.id];
          if (!target || target.view !== activeView || !target.canLoad()) return;
          entry.target.disabled = true;
          target.load();
        });
      },
      { root: null, rootMargin: "360px 0px", threshold: 0.01 },
    );
  }
  autoLoadObserver.disconnect();
  Object.keys(autoLoadTargets).forEach((id) => {
    const button = document.getElementById(id);
    if (button) autoLoadObserver.observe(button);
  });
}

async function pollQueueStatus() {
  const status = await getJson(`${API_BASE}/queue/status`);
  renderQueueStatus(status);
  if (activeView === "progress") {
    renderProgress();
    renderQueueStatus(status);
  }
  if (queueLogMode === "global" && status.running) {
    setProgressRunButtonState(status.cancel_requested ? "running" : "running", status.cancel_requested ? "暂停中..." : "暂停处理");
  }
  if (!status.running) {
    clearInterval(queueStatusTimer);
    queueStatusTimer = null;
    await loadApiData();
    renderAll();
    setView("progress");
    renderQueueStatus(status);
    const failedText = status.failed?.length ? `，失败 ${status.failed.length} 条` : "";
    const resultText = getQueueResultText(status);
    setProgressMessage(resultText || `自动处理完成：成功 ${status.processed?.length || 0} 条${failedText}，剩余 ${status.remaining ?? 0} 条。`, status.failed?.length ? "warn" : "ok");
    if (queueLogMode === "global") {
      setProgressRunButtonState("idle", "自动处理剩余");
    }
  }
}

async function startQueueJob(limit = 20) {
  requireAdminAction();
  setProgressMessage(`自动处理中：最多 ${limit} 条，按队列串行执行...`);
  setProgressRunButtonState("starting", "启动中...");
  queueLogMode = "global";
  activeProgressLogVideoId = null;
  if (queueLogPanel) queueLogPanel.hidden = false;
  const status = await postJson(`${API_BASE}/queue/start`, {
    limit,
    delay_seconds: 120,
  });
  renderQueueStatus(status);
  if (queueStatusTimer) clearInterval(queueStatusTimer);
  queueStatusTimer = setInterval(() => {
    pollQueueStatus().catch((error) => setProgressMessage(`读取队列进度失败：${error.message}`, "error"));
  }, 2000);
  await pollQueueStatus();
}

async function cancelQueueJob() {
  requireAdminAction();
  setProgressMessage("正在请求暂停队列...");
  setProgressRunButtonState("starting", "暂停中...");
  const status = await postJson(`${API_BASE}/queue/cancel`, {});
  renderQueueStatus(status);
  setProgressRunButtonState(status.running ? "running" : "idle", status.running ? "暂停中..." : "自动处理剩余");
  setProgressMessage(status.running ? "已请求暂停，当前步骤结束后停止队列。" : "当前没有运行中的队列。", status.running ? "warn" : "ok");
  if (!queueStatusTimer && status.running) {
    queueStatusTimer = setInterval(() => {
      pollQueueStatus().catch((error) => setProgressMessage(`读取队列进度失败：${error.message}`, "error"));
    }, 2000);
  }
  return status;
}

async function startVideoRetryJob(videoId, force = false) {
  requireAdminAction();
  queueLogMode = "row";
  activeProgressLogVideoId = videoId;
  if (queueLogPanel) queueLogPanel.hidden = true;
  lastQueueStatus = {
    job_id: "starting",
    running: true,
    logs: ["[--:--:--] 正在启动重试任务..."],
    processed: [],
    failed: [],
    remaining: null,
  };
  renderProgress();
  setProgressMessage("正在从获取文案开始重试...");
  let status;
  try {
    status = await postJson(`${API_BASE}/videos/${videoId}/retry-full/start`, { force });
  } catch (error) {
    lastQueueStatus = {
      job_id: "start_failed",
      running: false,
      logs: [`[--:--:--] 重试任务启动失败：${error.message}`],
      processed: [],
      failed: [{ video_id: videoId, error: error.message }],
      remaining: null,
    };
    renderProgress();
    renderQueueStatus(lastQueueStatus);
    throw error;
  }
  renderQueueStatus(status);
  if (queueStatusTimer) clearInterval(queueStatusTimer);
  queueStatusTimer = setInterval(() => {
    pollQueueStatus().catch((error) => setProgressMessage(`读取重试进度失败：${error.message}`, "error"));
  }, 2000);
  await pollQueueStatus();
}

function createNavigationEntryKey() {
  return `${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

function rememberNavigationPosition() {
  if (!navigationEntryKey) return;
  // Store reading position, not business data: returning must not resurrect deleted cards.
  navigationPositions.set(navigationEntryKey, {
    top: window.scrollY,
    left: window.scrollX,
    deletedTab: activeView === "deleted" ? activeDeletedTab : null,
    openClaims: [...document.querySelectorAll(`#${activeView}-view .claim-more[open]`)]
      .map((element) => element.closest("[data-claim-id]")?.dataset.claimId).filter(Boolean),
  });
}

function restoreNavigationPosition(position) {
  const openClaims = new Set(position?.openClaims || []);
  document.querySelectorAll(`#${activeView}-view .claim-more`).forEach((element) => {
    element.open = openClaims.has(element.closest("[data-claim-id]")?.dataset.claimId);
  });
  const key = navigationEntryKey;
  const scroll = () => {
    if (key === navigationEntryKey) window.scrollTo({ left: position?.left || 0, top: position?.top || 0, behavior: "instant" });
  };
  scroll();
  window.requestAnimationFrame(scroll);
}

function setView(view, options = {}) {
  if (!viewNames.has(view)) {
    view = "overview";
  }
  if (view === "detail" && (options.deletedVideo || options.updateHash === false && history.state?.deletedVideo)
      && adminSessionLoaded && !adminSession.authenticated) {
    history.replaceState({ view: "overview" }, "", "#overview");
    view = "overview";
    options = { ...options, updateHash: false };
  }
  if (ADMIN_VIEWS.has(view) && !adminSession.authenticated) {
    // Preserve a bookmarked admin view only while the initial session check is pending.
    if (adminSessionLoaded) history.replaceState({ view: "overview" }, "", "#overview");
    view = "overview";
    options = { ...options, updateHash: false };
  }
  const changedView = activeView !== view;
  if (changedView) {
    document.querySelectorAll('.claim-promotion-notice:has([aria-expanded="true"])')
      .forEach((notice) => setClaimPromotionNotice(notice, false));
  }
  rememberNavigationPosition();
  activeView = view;
  if (view === "deleted" && options.historyState) {
    activeDeletedTab = navigationPositions.get(options.historyState.entryKey)?.deletedTab || activeDeletedTab;
  }
  document.querySelectorAll(".view").forEach((el) => el.classList.remove("active"));
  document.querySelector(`#${view}-view`).classList.add("active");
  document.querySelectorAll(".nav-item").forEach((button) => {
    button.classList.toggle("active", button.dataset.view === view);
  });
  pageTitle.textContent = viewTitles[view];
  if (openIngestButton) {
    openIngestButton.hidden = view !== "sources" || !adminSession.authenticated;
  }
  if (view !== "sources" && ingestPanel) {
    ingestPanel.hidden = true;
  }
  if (view !== "detail") {
    const promotionEditor = document.querySelector("#promotion-editor");
    if (promotionEditor) promotionEditor.open = false;
  }
  if (options.updateHash !== false && (window.location.hash !== `#${view}` || (view === "detail" && history.state?.videoId !== selectedVideoId))) {
    const returnEntryKey = navigationEntryKey;
    navigationEntryKey = createNavigationEntryKey();
    history[options.replaceHistory ? "replaceState" : "pushState"]({ view, entryKey: navigationEntryKey, videoId: view === "detail" ? selectedVideoId : null,
      deletedVideo: view === "detail" && Boolean(options.deletedVideo),
      returnEntryKey, returnView: options.returnView || null }, "", `#${view}`);
  } else if (options.historyState) {
    navigationEntryKey = options.historyState.entryKey;
  }
  if (view === "knowledge" && options.historyState) {
    pendingKnowledgeReturnPosition = navigationPositions.get(navigationEntryKey) || null;
  } else if (changedView) {
    pendingKnowledgeReturnPosition = null;
  }
  if (options.render !== false) {
    renderCurrentView();
  }
  if (options.historyState || changedView) {
    restoreNavigationPosition(options.historyState ? navigationPositions.get(navigationEntryKey) : null);
  }
  updateKnowledgeBackToTop();
  if (view === "settings" && options.load !== false) loadTranscriptSettings();
  if (view === "sources" && options.load !== false && adminSession.authenticated) {
    refreshDouyinLoginStatus().catch((error) => console.info("Douyin login check failed:", error.message));
    loadSourcePerformance();
  }
  if (view === "deleted" && options.load !== false && !(options.historyState && deletedItems.loaded)) {
    loadDeletedItems();
  }
}

function syncViewFromHash() {
  const view = window.location.hash.replace(/^#/, "") || "overview";
  const nextView = viewNames.has(view) ? view : "overview";
  let state = history.state;
  if (state?.entryKey === navigationEntryKey && nextView === activeView) return;
  if (!state?.entryKey || state.view !== nextView) {
    state = { view: nextView, entryKey: createNavigationEntryKey() };
    history.replaceState(state, "");
  }
  if (nextView === "detail" && state.videoId) selectedVideoId = state.videoId;
  setView(nextView, { updateHash: false, historyState: state });
  if (nextView === "detail" && selectedVideoId) loadSelectedVideoDetail();
}

async function loadSelectedVideoDetail() {
  const videoId = selectedVideoId;
  const requestId = ++detailLoadRequestId;
  detailLoadError = "";
  detailLoadingId = videoId;
  renderDetail();
  try {
    if (isDeletedVideoDetail()) await loadDeletedVideoDetail(videoId);
    else await loadVideoDetail(videoId);
  } catch (error) {
    if (requestId === detailLoadRequestId && selectedVideoId === videoId) detailLoadError = error.message;
  } finally {
    if (requestId === detailLoadRequestId && selectedVideoId === videoId) {
      detailLoadingId = null;
      if (activeView === "detail") renderDetail();
    }
  }
}

function enforceHashView() {
  const hashView = window.location.hash.replace(/^#/, "");
  if (viewNames.has(hashView) && activeView !== hashView) {
    setView(hashView, { updateHash: false });
  }
}

function renderOverview() {
  document.querySelector("#metric-stages").textContent = stages.length;
  document.querySelector("#metric-notes").textContent = overviewProcessNodes.length;
  document.querySelector("#metric-dos").textContent = firstKnownCount(apiStats.videoCount, videos.length);
  document.querySelector("#metric-donts").textContent = getClaimTotal();

  const colors = ["#0f7a4d", "#e33b2f", "#1456a3", "#f2c230"];
  document.querySelector("#timeline").innerHTML = stages
    .map((stage, index) => {
      const count = getKnowledgeCategoryCount({ type: "stage", value: stage.name }) ?? "…";
      return `
        <article class="timeline-card" style="--accent: ${colors[index % colors.length]}" data-knowledge-stage="${escapeAttr(stage.name)}">
          <button type="button" aria-label="查看${escapeAttr(stage.name)}" data-knowledge-stage="${escapeAttr(stage.name)}"></button>
          <span class="stage-number" aria-hidden="true">${index + 1}</span>
          <h3>${escapeHtml(stage.name)}</h3>
          <div class="timeline-meta">
            <span class="chip">${count} 条观点</span>
            <span class="chip risk-chip" data-risk="${escapeAttr(stage.risk)}">风险 ${escapeHtml(stage.risk)}</span>
          </div>
        </article>
      `;
    })
    .join("");
}

function sourceHomepageLabel(source) {
  const platform = String(source.platform || "");
  if (/抖音|douyin/i.test(platform)) return "跳转到抖音主页";
  if (/小红书|xiaohongshu/i.test(platform)) return "跳转到小红书主页";
  if (/B站|bilibili/i.test(platform)) return "跳转到B站主页";
  return platform && platform !== "待识别" ? `跳转到${platform}主页` : "跳转到来源主页";
}

function renderSourcePerformanceChart(item) {
  const sampleCount = normalizeCount(item.sample_count) || 0;
  const withCards = Math.min(sampleCount, normalizeCount(item.videos_with_cards) || 0);
  const share = sampleCount ? withCards / sampleCount * 100 : 0;
  const content = item.content_counts || {};
  const segments = [["not_ad", "普通"], ["advertising", "推广"], ["uncertain", "存疑"],
    ["error", "判定失败"], ["unknown", "未判定"]]
    .map(([key, label]) => ({ key, label, count: normalizeCount(content[key]) || 0 }))
    .filter(segment => segment.count > 0);
  const contentLabel = segments.map(segment => `${segment.label} ${segment.count} 条`).join("，");
  let offset = 0;
  return `<div class="source-performance-chart">
    <div class="source-performance-yield">
      <svg class="source-performance-ring" viewBox="0 0 100 100" role="img" aria-label="${sampleCount
        ? `有卡视频 ${withCards} / ${sampleCount} 条` : "暂无视频样本"}">
        <circle class="performance-ring-track" cx="50" cy="50" r="41" />
        <circle class="performance-ring-value" cx="50" cy="50" r="41" pathLength="100" stroke-dasharray="${share} 100" transform="rotate(-90 50 50)" />
        <text class="performance-ring-number" x="50" y="46">${sampleCount ? `${withCards}/${sampleCount}` : "—"}</text>
        <text class="performance-ring-label" x="50" y="64">${sampleCount ? "有卡视频" : "暂无样本"}</text>
      </svg>
      <dl class="source-performance-key-metrics">
        <div><dt>知识卡</dt><dd>${normalizeCount(item.retained_cards) || 0}<small> 张</small></dd></div>
        <div><dt>技术异常</dt><dd>${normalizeCount(item.technical_videos) || 0}<small> 条</small></dd></div>
      </dl>
    </div>
    <div class="source-performance-content">
      <svg class="source-performance-bar" viewBox="0 0 100 8" preserveAspectRatio="none" role="img" aria-label="内容判定：${contentLabel || "暂无判定数据"}">
        <rect class="performance-bar-track" width="100" height="8" />
        ${segments.map(segment => {
          const width = sampleCount ? segment.count / sampleCount * 100 : 0;
          const rect = `<rect class="performance-content-segment" data-content="${segment.key}" x="${offset}" width="${width}" height="8"><title>${segment.label} ${segment.count} 条</title></rect>`;
          offset += width;
          return rect;
        }).join("")}
      </svg>
      <div class="source-performance-legend">${segments.length ? segments.map(segment =>
        `<span><i data-content="${segment.key}" aria-hidden="true"></i>${segment.label}<strong>${segment.count}</strong></span>`).join("")
        : "暂无内容判定"}</div>
    </div>
  </div>`;
}

function renderSourcePerformance(source) {
  if (!adminSession.authenticated || adminSession.read_only || window.DECOR_PUBLIC_LIBRARY) return "";
  const item = sourcePerformance.sources.get(source.id);
  if (sourcePerformance.status === "error") return `<div class="source-performance-message" data-source-performance>
    近期入库表现暂不可用 <button type="button" class="text-button" data-retry-source-performance>重试</button></div>`;
  if (!item) return `<div class="source-performance-message" data-source-performance>${sourcePerformance.status === "loading"
    ? "正在读取近期入库表现…" : "暂无近期统计"}</div>`;
  return `<details class="source-performance" data-source-performance="${escapeAttr(source.id)}" ${expandedSourcePerformance.has(source.id) ? "open" : ""}>
    <summary><span>近期入库表现<small class="source-performance-brief">${Number(item.videos_with_cards)} 条有卡 · ${Number(item.retained_cards)} 张知识卡</small></span><span class="source-performance-coverage" title="最近已采集的 ${Number(item.sample_count)} 条视频">${Number(item.sample_count)} / 10</span></summary>
    <div class="source-performance-body">
      ${renderSourcePerformanceChart(item)}
    </div>
  </details>`;
}

function renderSources() {
  if (adminSession.authenticated) document.querySelectorAll(".source-performance").forEach(element => {
    const id = element.dataset.sourcePerformance;
    // A refresh can precede the native toggle event; preserve the actual open state.
    if (element.open) expandedSourcePerformance.add(id);
    else expandedSourcePerformance.delete(id);
  });
  const focused = document.activeElement;
  const focusedSourceId = focused?.matches(".source-performance summary")
    ? focused.closest("[data-source-performance]")?.dataset.sourcePerformance : null;
  const sourceSummary = document.querySelector("#source-summary");
  if (sourceSummary) {
    const total = sources.reduce((sum, source) => sum + (normalizeCount(source.video_count) ?? 0), 0);
    sourceSummary.textContent = `${sources.length} 个来源 · ${total} 条视频${adminSession.authenticated ? " · 更新跳过置顶" : ""}`;
  }
  const loginChecking = douyinLoginChecking || douyinLoginStatus.running;
  const loginBusy = douyinLoginStatus.status === "busy";
  const loginUnknown = ["idle", "unknown"].includes(douyinLoginStatus.status) || douyinLoginStatus.logged_in == null;
  const loginType = loginChecking || loginUnknown ? "warn" : douyinLoginStatus.logged_in ? "done" : "";
  const loginLabel = loginChecking ? "登录检测中" : loginBusy ? "浏览器正忙" : loginUnknown ? "登录态待确认"
    : douyinLoginStatus.logged_in ? "登录态已保存" : "抖音未登录";
  const platformOrder = ["抖音", "小红书", "B站", "待识别"];
  const groupedSources = sources.reduce((acc, source) => {
    const platform = source.platform || "待识别";
    if (!acc[platform]) acc[platform] = [];
    acc[platform].push(source);
    return acc;
  }, {});
  const orderedPlatforms = [
    ...platformOrder.filter((platform) => groupedSources[platform]),
    ...Object.keys(groupedSources).filter((platform) => !platformOrder.includes(platform)),
  ];
  const renderSourceCard = (source) => `
    <article class="source-card" role="button" tabindex="0" data-source-filter-id="${escapeAttr(source.id)}" data-source-filter-name="${escapeAttr(source.name)}">
      <div class="source-card-heading">
        <div class="source-card-identity">
          <h3>${escapeHtml(source.name)}</h3>
          <a class="source-home-link" href="${safeUrl(source.profile_url)}" target="_blank" rel="noreferrer" aria-label="${escapeAttr(sourceHomepageLabel(source))}" data-tooltip="${escapeAttr(sourceHomepageLabel(source))}">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M14 3h7v7M21 3 10 14"/><path d="M10 3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-5"/></svg>
          </a>
        </div>
        <span class="status ${source.status === "active" ? "done" : ""}">${escapeHtml(getSourceStatusLabel(source.status))}</span>
      </div>
      <div class="timeline-meta">
        <span class="chip">${Number(source.video_count || 0)} 条视频</span>
        <span class="chip">${Number(source.pending_count || 0)} 条文案待提取</span>
        <span class="chip">${Number(source.claim_count || 0)} 条观点</span>
      </div>
      ${renderSourcePerformance(source)}
      ${adminSession.authenticated ? `<footer data-admin-only>
        <button class="primary-button small red" type="button" data-update-source-id="${escapeAttr(source.id)}" ${adminActionAttributes()}>更新 5 条</button>
      </footer>` : ""}
    </article>
  `;
  const sourceGroups =
    orderedPlatforms.length > 0
      ? orderedPlatforms
          .map((platform) => {
            const groupSources = groupedSources[platform];
            const groupVideoCount = groupSources.reduce((sum, source) => sum + (source.video_count || 0), 0);
            const groupPendingCount = groupSources.reduce((sum, source) => sum + (source.pending_count || 0), 0);
            const isDouyin = platform.includes("抖音");
            const loginProfileUrl = groupSources.find((source) => source.profile_url)?.profile_url || "";
            return `
              <section class="source-group">
                <header class="source-group-head">
                  <div class="source-group-summary">
                    <h3>${escapeHtml(platform)}</h3>
                    ${isDouyin && adminSession.authenticated ? `<span class="status ${loginType}">${escapeHtml(loginLabel)}</span>` : ""}
                    <p>${groupSources.length} 个博主 / ${groupVideoCount} 条视频 / ${groupPendingCount} 条文案待提取</p>
                  </div>
                  ${
                    isDouyin && adminSession.authenticated
                      ? `<div class="source-group-actions" data-admin-only>
                          <button class="primary-button small" type="button" id="check-douyin-login" ${loginChecking ? "disabled" : ""}>${loginChecking ? "检测中…" : "检查登录态"}</button>
                          <button class="primary-button small" type="button" data-douyin-login-url="${escapeAttr(loginProfileUrl)}" ${adminActionAttributes()}>登录抖音</button>
                        </div>`
                      : ""
                  }
                </header>
                <div class="source-card-grid">
                  ${groupSources.map(renderSourceCard).join("")}
                </div>
              </section>
            `;
          })
          .join("")
      : `<article class="result-card"><h3>暂无来源</h3></article>`;
  document.querySelector("#source-grid").innerHTML = sourceGroups;
  if (focusedSourceId) [...document.querySelectorAll(".source-performance")]
    .find(element => element.dataset.sourcePerformance === focusedSourceId)
    ?.querySelector(":scope > summary")?.focus({ preventScroll: true });
}

function renderPipeline() {
  document.querySelector("#pipeline").innerHTML = getPipeline()
    .map(
      ([label, count]) => `
        <article class="pipeline-card">
          <span>${escapeHtml(label)}</span>
          <strong>${Number(count || 0)}</strong>
        </article>
      `,
    )
    .join("");
}

function getVideoFilterCounts() {
  // Use the full catalog, so loading a page or selecting a creator cannot hide options.
  const platformRows = videoFacets?.platforms || sources.map((source) => ({
    platform: source.platform,
    video_count: source.video_count,
  }));
  const creatorRows = videoFacets?.creators || sources.map((source) => ({
    platform: source.platform,
    creator: source.name,
    video_count: source.video_count,
  }));
  const platforms = new Map();
  const creators = new Map();
  for (const row of platformRows) {
    if (!row.platform) continue;
    platforms.set(row.platform, (platforms.get(row.platform) || 0) + (normalizeCount(row.video_count) ?? 0));
  }
  for (const row of creatorRows) {
    if (!row.creator || (activeVideoPlatform !== "全部" && row.platform !== activeVideoPlatform)) continue;
    creators.set(row.creator, (creators.get(row.creator) || 0) + (normalizeCount(row.video_count) ?? 0));
  }
  const total = firstKnownCount(videoFacets?.total, apiStats.videoCount, [...platforms.values()].reduce((sum, count) => sum + count, 0));
  return { platforms, creators, total };
}

function renderVideoFilters() {
  const panel = document.querySelector("#video-filter-panel");
  if (!panel) return;
  const counts = getVideoFilterCounts();
  const platforms = ["全部", ...counts.platforms.keys()];
  const creators = ["全部", ...counts.creators.keys()];
  const platformTotal = activeVideoPlatform === "全部" ? counts.total : (counts.platforms.get(activeVideoPlatform) || 0);
  panel.innerHTML = `
    <section class="video-filter-group" aria-label="按平台筛选">
      <span>平台</span>
      <div>
        ${platforms
          .map((platform) => {
            const count = platform === "全部" ? counts.total : counts.platforms.get(platform);
            return `
              <button class="filter-button ${activeVideoPlatform === platform ? "active" : ""}" type="button" data-video-platform="${escapeAttr(platform)}" data-video-count="${count}">
                ${escapeHtml(platform)} ${count}
              </button>
            `;
          })
          .join("")}
      </div>
    </section>
    <section class="video-filter-group" aria-label="按博主筛选">
      <span>博主</span>
      <div>
        ${creators
          .map((creator) => {
            const count = creator === "全部" ? platformTotal : counts.creators.get(creator);
            return `
              <button class="filter-button ${activeVideoCreator === creator ? "active" : ""}" type="button" data-video-creator="${escapeAttr(creator)}" data-video-count="${count}">
                ${escapeHtml(creator)} ${count}
              </button>
            `;
          })
          .join("")}
      </div>
    </section>
  `;
}

function renderVideos() {
  renderPipeline();
  renderVideoFilters();
  const visibleVideos = sortVideosByPublishTime(
    videos.filter((video) => {
      const sourceMatched = !activeSourceFilter || video.sourceId === activeSourceFilter.id || video.creator === activeSourceFilter.name;
      const platformMatched = activeVideoPlatform === "全部" || video.platform === activeVideoPlatform;
      const creatorMatched = activeVideoCreator === "全部" || video.creator === activeVideoCreator;
      return sourceMatched && platformMatched && creatorMatched;
    }),
  );
  const filterNotice = activeSourceFilter
    ? `
      <article class="video-filter-notice">
        <span>当前来源：${escapeHtml(activeSourceFilter.name)}</span>
        <button class="primary-button small" type="button" id="clear-source-filter">显示全部</button>
      </article>
    `
    : "";
  let emptyState = `<article class="result-card"><h3>暂无视频</h3></article>`;
  if (!visibleVideos.length && apiLoadState.status === "loading") {
    emptyState = `<article class="result-card"><h3>正在加载视频…</h3></article>`;
  } else if (!visibleVideos.length && apiLoadState.status === "error") {
    emptyState = `
      <article class="result-card">
        <h3>${apiHealthState.dbAvailable === false ? "数据库当前不可用" : "视频接口连接失败"}</h3>
        <p>${escapeHtml(apiLoadState.error || "本地服务暂时不可用")}。</p>
        <footer>
          <button class="primary-button small red" type="button" id="retry-api-load">重新加载</button>
        </footer>
      </article>
    `;
  }
  const videoCards = visibleVideos.length
    ? visibleVideos
        .map((video) => {
          const hasTranscript = hasVideoTranscript(video);
          const hasClaims = video.claimCount > 0 || video.claims.length > 0;
          const isFiltered = video.status === "claims_filtered";
          const extracting = Boolean(videoExtractions.get(video.id)?.running);
          const extractLabel = extracting ? "提取中" : "提取观点";
          const extractBlocked = extracting || hasClaims || isFiltered || !hasTranscript;
          const transcriptLabel = hasTranscript ? "文案已保存" : video.status === "transcript_failed" ? "文案获取失败" : "文案未获取";
          const claimsLabel = extracting ? "观点提取中" : hasClaims ? "观点已提取" : isFiltered ? "观点已过滤" : "观点未提取";
          return `
        <article class="video-card">
          <div>
            <div class="video-content-status" aria-label="文案、观点与推广状态">
              ${renderVideoStateBadge("document", "文案", hasTranscript ? "done" : video.status === "transcript_failed" ? "failed" : "missing", transcriptLabel)}
              ${renderVideoStateBadge("claims", "观点", extracting ? "running" : hasClaims ? "done" : "missing", claimsLabel)}
              ${renderAdBadge(video)}
            </div>
            <h3>${escapeHtml(video.title)}</h3>
            <div class="video-share-link">
              <span class="video-share-label">分享链接：</span>
              <a href="${safeUrl(video.sourceUrl)}" target="_blank" rel="noreferrer" title="${escapeAttr(video.sourceUrl)}">${sanitizeUrl(video.sourceUrl) === "#" ? "暂无链接" : escapeHtml(video.sourceUrl)}</a>
              <button class="copy-link-button" type="button" data-copy-source-url="${escapeAttr(video.sourceUrl)}" ${sanitizeUrl(video.sourceUrl) === "#" ? "disabled" : ""} aria-label="复制分享链接" title="复制分享链接">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="8" y="8" width="12" height="13" rx="2"/><path d="M16 8V5a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h3"/></svg>
              </button>
              <span class="copy-link-feedback" role="status"></span>
            </div>
            <p>${escapeHtml(video.creator)} / ${escapeHtml(video.platform)}</p>
          </div>
          <div class="timeline-meta">
            <span class="chip">${escapeHtml(video.publishTime)}</span>
            <button class="chip video-claims-trigger" type="button" data-video-claims-id="${escapeAttr(video.id)}" aria-haspopup="dialog" aria-controls="video-claims-dialog" aria-label="查看${escapeAttr(video.title)}的观点">${video.claimCount} 条观点</button>
            ${video.excludedClaimCount && adminSession.authenticated && !adminSession.read_only && !window.DECOR_PUBLIC_LIBRARY ? `<button class="video-filtered-trigger" type="button" data-video-exclusions-id="${escapeAttr(video.id)}" aria-haspopup="dialog" aria-controls="video-exclusions-dialog" aria-label="查看 ${video.excludedClaimCount} 条过滤记录" title="查看过滤的原文和原因">${videoBadgeSvg("filter")}<span>过滤 ${video.excludedClaimCount}</span><span aria-hidden="true">›</span></button>` : ""}
          </div>
          <footer>
            <button class="primary-button small" type="button" data-video-id="${escapeAttr(video.id)}">查看详情</button>
            ${adminSession.authenticated && hasTranscript && !hasClaims && !isFiltered ? `<button class="primary-button small red" type="button" data-extract-video-id="${escapeAttr(video.id)}" ${adminActionAttributes(extractBlocked)}>${escapeHtml(extractLabel)}</button>` : ""}
            ${
              adminSession.authenticated
                ? `<button class="primary-button small red" type="button" data-delete-video-id="${escapeAttr(video.id)}">删除视频</button>`
                : ""
            }
          </footer>
        </article>
      `;
        })
        .join("")
    : emptyState;
  const paginationCard =
    visibleVideos.length || videoPageState.total > 0 || videoPageState.loading || videoPageState.error
      ? `
        <article class="video-filter-notice">
          <span>已显示 ${visibleVideos.length} / ${videoPageState.total} 条视频</span>
          ${
            videoPageState.error
              ? `<span>加载失败：${escapeHtml(videoPageState.error)}</span><button class="primary-button small" type="button" id="retry-video-page">重试加载</button>`
              : videoPageState.loading
                ? `<span>正在加载...</span>`
                : !videoPageState.hasMore && visibleVideos.length < videoPageState.total
                  ? `<span>列表数据待同步</span><button class="primary-button small" type="button" id="retry-video-page">重新同步列表</button>`
                : videoPageState.hasMore
                  ? `<button class="primary-button small" type="button" id="load-more-videos">加载更多</button>`
                  : `<span>已加载全部</span>`
          }
        </article>
      `
      : "";
  document.querySelector("#video-grid").innerHTML = filterNotice + videoCards + paginationCard;
  setupAutoLoadMore();
  if (activeView === "videos" && !videoPageState.loading && !videoPageState.error && !videoPageState.hasMore && visibleVideos.length < videoPageState.total && !videoListRepairPending && videoListRepairAttemptId !== videoLoadRequestId) {
    // Repair stale/mixed cached data once; never label a partial list as complete.
    const requestId = videoLoadRequestId;
    videoListRepairPending = true;
    queueMicrotask(() => {
      videoListRepairPending = false;
      if (activeView !== "videos" || videoPageState.loading || requestId !== videoLoadRequestId) return;
      const repair = loadVideoPage({ preserveLoaded: true });
      videoListRepairAttemptId = videoLoadRequestId;
      repair.catch((error) => console.info("Video list resync failed:", error.message));
    });
  }
}

function getVideoProgressState(video) {
  if (video.adReview?.decision === "advertising") return { key: "已完成", label: "推广 · 已跳过", step: 3, retry: "完成" };
  if (["uncertain", "error"].includes(video.adReview?.decision)) return { key: "待确认", label: "疑似推广", step: 2, retry: "重试" };
  const hasTranscript = hasVideoTranscript(video);
  const claimCount = video.claimCount || video.claims.length;
  if (video.status === "claims_filtered" && (!video.lastError || video.lastError.startsWith("无有效内容"))) {
    return { key: "已完成", label: "已过滤", step: 3, retry: "完成" };
  }
  if (video.status === "transcript_failed" || video.lastError) {
    return { key: "失败", label: "失败", step: 1, retry: "重试" };
  }
  if (video.excludedClaimCount > 0) return { key: "已完成", label: claimCount > 0 ? "已完成" : "已过滤", step: 3, retry: "完成" };
  if (!video.sourceUrl && !video.shareUrl) {
    return { key: "缺链接", label: "缺链接", step: 0, retry: "获取链接" };
  }
  if (claimCount > 0) {
    return { key: "已完成", label: "已完成", step: 3, retry: "完成" };
  }
  if (hasTranscript) {
    return { key: "待观点", label: "待提取观点", step: 2, retry: "重试" };
  }
  return { key: "待文案", label: "待提取文案", step: 1, retry: "重试" };
}

function renderProgress() {
  document.querySelectorAll(".progress-note[data-progress-note-id]").forEach(element => {
    if (element.open) expandedProgressNotes.add(element.dataset.progressNoteId);
    else expandedProgressNotes.delete(element.dataset.progressNoteId);
  });
  const sortedProgressVideos = sortVideosByPublishTime(progressVideos.length ? progressVideos : videos);
  const localCounts = sortedProgressVideos.reduce(
    (acc, video) => {
      const state = getVideoProgressState(video);
      acc[state.key] = (acc[state.key] || 0) + 1;
      acc["全部"] += 1;
      return acc;
    },
    { 全部: 0, 缺链接: 0, 待文案: 0, 待观点: 0, 已完成: 0, 失败: 0 },
  );
  const counts = progressSummary || localCounts;
  const tabs = ["全部", "缺链接", "待文案", "待观点", "待确认", "已完成", "失败"];
  const progressTabLabels = { 待文案: "待提取文案", 待观点: "待提取观点" };
  const progressTabIcons = { 全部: "filter", 缺链接: "cross", 待文案: "document", 待观点: "claims", 待确认: "promotion", 已完成: "check", 失败: "warning" };
  document.querySelector("#progress-tabs").innerHTML = tabs
    .map(
      (tab) => `
        <button class="filter-button ${activeProgressFilter === tab ? "active" : ""}" type="button" data-progress-filter="${escapeAttr(tab)}" aria-pressed="${activeProgressFilter === tab}">
          ${videoBadgeSvg(progressTabIcons[tab])}<span>${escapeHtml(progressTabLabels[tab] || tab)}</span><span class="progress-filter-count">${counts[tab] || 0}</span>
        </button>
      `,
    )
    .join("");

  const visibleVideos = sortedProgressVideos;
  const paginationCard =
    visibleVideos.length || progressPageState.loading || progressPageState.error
      ? `
        <article class="video-filter-notice">
          <span>已显示 ${Math.min(progressVideos.length || visibleVideos.length, progressPageState.total || visibleVideos.length)} / ${
            progressPageState.total || visibleVideos.length
          } 条进度</span>
          ${
            progressPageState.error
              ? `<span>加载失败：${escapeHtml(progressPageState.error)}</span>`
              : progressPageState.loading
                ? `<span>正在加载...</span>`
                : progressPageState.hasMore
                  ? `<button class="primary-button small" type="button" id="load-more-progress">加载更多</button>`
                  : `<span>已加载全部</span>`
          }
        </article>
      `
      : "";

  document.querySelector("#progress-list").innerHTML = visibleVideos.length
    ? `${visibleVideos
        .map((video) => {
          const state = getVideoProgressState(video);
          const stageTags = renderProgressStageTags(video);
          const timeTags = renderProgressTimeTags(video);
          const live = getLiveProgressStage(video);
          const presentation = getProgressPresentation(video, state, live);
          const notice = presentation.tone === "running" ? null : getProgressNotice(video);
          const retryLabel = state.key === "缺链接" ? "补充来源" : state.key === "已完成" ? "重新处理" : "重试";
          const busy = Boolean(lastQueueStatus?.running);
          const rowLog =
            activeProgressLogVideoId === video.id
      ? `
                <details class="queue-log-panel row-log-panel" data-row-log-video-id="${escapeAttr(video.id)}" open>
                  <summary>
                    <span data-row-log-title>${escapeHtml(lastQueueStatus && lastQueueStatus.job_id ? getQueueResultText(lastQueueStatus) || "本条重试日志" : "本条重试日志")}</span>
                    <small data-row-log-meta>${escapeHtml(lastQueueStatus?.job_id ? `${lastQueueStatus.job_id} / ${lastQueueStatus.running ? "运行中" : "已结束"}` : "准备启动...")}</small>
                    <button class="log-follow-button" type="button" data-log-follow-bottom hidden>跳到底部</button>
                    <button class="log-close-button" type="button" data-close-row-log aria-label="关闭重试日志">关闭</button>
                  </summary>
                  <pre data-row-log-body>${escapeHtml(lastQueueStatus?.logs?.length ? formatQueueLogs(lastQueueStatus.logs) : "[--:--:--] 等待重试启动...")}</pre>
                </details>
              `
              : "";
          return `
            <article class="progress-card" data-progress-video-id="${escapeAttr(video.id)}" data-state="${presentation.tone}">
              <div class="progress-card-main">
                <div class="progress-card-heading">
                  <span class="progress-state${presentation.promotionState ? " video-state-badge video-promotion-badge" : ""}"${presentation.promotionState ? ` data-state="${presentation.promotionState}"` : ""}>${videoBadgeSvg(presentation.icon)}<span>${escapeHtml(presentation.label)}</span></span>
                  <h3 title="${escapeAttr(video.title)}">${escapeHtml(video.title)}</h3>
                </div>
                <div class="progress-card-meta">
                  <span class="progress-creator-line">${escapeHtml(video.creator || "博主未记录")}</span>
                  ${timeTags}
                  ${video.retryCount ? `<span class="progress-retry-count">重试 ${video.retryCount} 次</span>` : ""}
                </div>
                <div class="progress-steps" aria-label="处理阶段">${stageTags}</div>
                ${notice ? `<details class="progress-note" data-progress-note-id="${escapeAttr(video.id)}" ${expandedProgressNotes.has(video.id) ? "open" : ""}>
                  <summary><span class="progress-note-summary">${escapeHtml(notice.summary)}</span><span class="progress-note-toggle" aria-hidden="true">详情</span></summary>
                  <p>${escapeHtml(notice.detail)}</p>
                </details>` : ""}
              </div>
              <footer class="progress-card-actions">
                <button class="primary-button small" type="button" data-video-id="${escapeAttr(video.id)}">详情</button>
                ${adminSession.authenticated ? `<button class="primary-button small progress-retry-action" type="button" data-progress-retry-video-id="${escapeAttr(video.id)}" data-progress-retry-state="${escapeAttr(state.key)}" aria-label="${escapeAttr(state.key === "缺链接" ? "前往来源页补充链接" : "从获取文案开始重新处理")}" ${adminActionAttributes(busy)}>${presentation.tone === "running" ? "处理中" : retryLabel}</button>` : ""}
                ${
                  adminSession.authenticated
                    ? `<button class="primary-button small progress-delete-action" type="button" data-delete-video-id="${escapeAttr(video.id)}" aria-label="删除视频：${escapeAttr(video.title)}" title="删除视频">${videoBadgeSvg("delete")}</button>`
                    : ""
                }
              </footer>
            </article>
            ${rowLog}
          `;
        })
        .join("")}${paginationCard}`
    : `<article class="result-card"><h3>暂无待处理视频</h3></article>`;
  setupAutoLoadMore();
}

function applySourceFilter(sourceId, sourceName) {
  activeSourceFilter = {
    id: sourceId,
    name: sourceName,
  };
  activeVideoPlatform = "全部";
  activeVideoCreator = "全部";
  loadVideoPage();
  setView("videos");
}

let videoClaimsRequestId = 0;

function clearVideoExclusions() {
  exclusionRequestId += 1;
  const dialog = document.querySelector("#video-exclusions-dialog");
  dialog?.close();
  document.querySelector("#video-exclusions-dialog-content")?.replaceChildren();
  const title = document.querySelector("#video-exclusions-dialog-name");
  if (title) title.textContent = "";
  const count = document.querySelector("#video-exclusions-count");
  if (count) count.textContent = "";
}

async function openVideoExclusions(videoId) {
  if (!adminSession.authenticated || adminSession.read_only || window.DECOR_PUBLIC_LIBRARY) return;
  const dialog = document.querySelector("#video-exclusions-dialog");
  if (!dialog) return;
  const content = document.querySelector("#video-exclusions-dialog-content");
  const title = document.querySelector("#video-exclusions-dialog-name");
  const count = document.querySelector("#video-exclusions-count");
  const requestId = ++exclusionRequestId;
  const isCurrent = () => requestId === exclusionRequestId && dialog.open && adminSession.authenticated && !adminSession.read_only;
  title.textContent = videos.find(video => video.id === videoId)?.title || "";
  count.textContent = "";
  content.setAttribute("aria-busy", "true");
  content.innerHTML = '<p class="video-claims-notice" role="status">正在加载…</p>';
  if (!dialog.open) dialog.showModal();
  try {
    const response = await fetch(`${API_BASE}/admin/videos/${encodeURIComponent(videoId)}/exclusions`, { credentials: "include", cache: "no-store" });
    if (!isCurrent()) return;
    if (response.status === 401) {
      adminSession = { ...adminSession, authenticated: false };
      renderAdminSession();
      return;
    }
    if (!response.ok) throw new Error("读取失败");
    const payload = await response.json();
    if (!isCurrent()) return;
    title.textContent = payload.video.title;
    count.textContent = `${payload.total} 条`;
    content.innerHTML = payload.items.length ? `<ol class="video-exclusion-list">${payload.items.map(item => `<li>
      <header><span class="exclusion-action" data-action="${item.action === "字段省略" ? "field" : "content"}">${escapeHtml(item.action)}</span>${item.object ? `<h3>${escapeHtml(item.object)}</h3>` : ""}</header>
      <ul class="exclusion-reasons">${item.reasons.map(reason => `<li>${escapeHtml(reason)}</li>`).join("")}</ul>
      ${item.quotes.length ? item.quotes.map(quote => `<blockquote>${escapeHtml(quote)}</blockquote>`).join("") : '<p class="exclusion-missing-quote">未保存对应引句</p>'}
    </li>`).join("")}</ol>` : '<p class="video-claims-notice" role="status">当前文案没有过滤记录</p>';
  } catch (error) {
    if (!isCurrent()) return;
    content.innerHTML = `<div class="video-claims-notice" role="alert"><p>过滤记录加载失败</p><button class="primary-button small" type="button" data-video-exclusions-id="${escapeAttr(videoId)}">重试</button></div>`;
  } finally {
    if (isCurrent()) content.setAttribute("aria-busy", "false");
  }
}

async function openVideoClaims(videoId) {
  const dialog = document.querySelector("#video-claims-dialog");
  const content = document.querySelector("#video-claims-dialog-content");
  const title = document.querySelector("#video-claims-dialog-name");
  const video = videos.find((item) => item.id === videoId) || progressVideos.find((item) => item.id === videoId);
  const requestId = ++videoClaimsRequestId;
  title.textContent = video?.title || "视频观点";
  content.setAttribute("aria-busy", "true");
  content.innerHTML = '<p class="video-claims-notice" role="status">正在加载观点…</p>';
  if (!dialog.open) dialog.showModal();
  try {
    const detail = await fetchApiJson(`/videos/${encodeURIComponent(videoId)}`);
    if (!dialog.open || requestId !== videoClaimsRequestId) return;
    title.textContent = detail.video.title;
    const claims = (detail.claims || []).map(normalizeApiClaim);
    content.innerHTML = claims.length
      ? claims.map((claim) => renderClaimCard({ ...claim, videoId }, { allowDelete: false })).join("")
      : '<p class="video-claims-notice" role="status">暂无知识卡</p>';
  } catch (error) {
    if (!dialog.open || requestId !== videoClaimsRequestId) return;
    content.innerHTML = `<div class="video-claims-notice" role="alert"><p>观点加载失败：${escapeHtml(error.message)}</p><button class="primary-button small" type="button" data-video-claims-id="${escapeAttr(videoId)}">重试</button></div>`;
  } finally {
    if (requestId === videoClaimsRequestId) content.setAttribute("aria-busy", "false");
  }
}

function getAuthorStancePresentation(stance) {
  if (stance === "赞成") return { label: "作者赞成", state: "support" };
  if (stance === "反对") return { label: "作者反对", state: "oppose" };
  if (stance === "中性陈述") return { label: "作者中性陈述", state: "statement" };
  return { label: "作者态度未明确", state: "unknown" };
}

let claimPromotionNoticeSequence = 0;

const claimRelationLabels = { opposite: "不同观点", similar: "相近观点" };
const claimRelationGroups = { opposite: "opposite", conditions: "opposite", equivalent: "similar", similar: "similar" };
const claimRelationSvgs = {
  opposite: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 7h16m-4-4 4 4-4 4M20 17H4m4-4-4 4 4 4"/></svg>',
  similar: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 7h16m-4-4 4 4-4 4M4 17h16m-4-4 4 4-4 4"/></svg>',
};

function groupClaimRelationCounts(counts = {}) {
  const grouped = { opposite: 0, similar: 0 };
  for (const [kind, value] of Object.entries(counts)) {
    const group = claimRelationGroups[kind];
    const count = Number(value);
    if (group && Number.isFinite(count) && count > 0) grouped[group] += count;
  }
  return grouped;
}

function setClaimRelationMark(kind) {
  const mark = document.querySelector("#claim-relations-mark");
  const group = claimRelationGroups[kind] || "similar";
  mark.innerHTML = claimRelationSvgs[group];
  mark.dataset.kind = group;
}

let claimRelationsRequestId = 0;
let claimRelationsPayload = null;
let claimRelationsKind = null;
let claimRelationsIndex = 0;

function renderClaimRelations(kind, index = 0) {
  const content = document.querySelector("#claim-relations-content");
  const payload = claimRelationsPayload;
  if (!payload) return;
  const counts = groupClaimRelationCounts(payload.relations.reduce((result, row) => {
    result[row.kind] = (result[row.kind] || 0) + 1;
    return result;
  }, {}));
  const requested = claimRelationGroups[kind];
  const selected = counts[requested] ? requested : Object.keys(counts).find(key => counts[key]);
  const rows = payload.relations.filter(row => claimRelationGroups[row.kind] === selected && selected);
  claimRelationsKind = selected;
  claimRelationsIndex = Math.max(0, Math.min(index, rows.length - 1));
  const row = rows[claimRelationsIndex];
  const reasonLabels = { opposite: "差异", similar: "共同点" };
  setClaimRelationMark(selected);
  content.innerHTML = `<div class="claim-comparison-toolbar">
      <div class="claim-relation-tabs" role="group" aria-label="关联类型">${Object.entries(claimRelationLabels)
        .filter(([key]) => counts[key]).map(([key, label]) => `<button class="claim-relation-tab" type="button" data-claim-relation-tab="${key}" aria-pressed="${key === selected}">${claimRelationSvgs[key]}${label}<span>${counts[key]}</span></button>`).join("")}</div>
      ${rows.length > 1 ? `<nav class="claim-comparison-pager" aria-label="切换关联观点">
        <button type="button" data-claim-relation-step="-1" aria-label="上一条关联观点" ${claimRelationsIndex === 0 ? "disabled" : ""}><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m14 6-6 6 6 6"/></svg></button>
        <span role="status">${claimRelationsIndex + 1}<span> / ${rows.length}</span></span>
        <button type="button" data-claim-relation-step="1" aria-label="下一条关联观点" ${claimRelationsIndex === rows.length - 1 ? "disabled" : ""}><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m10 6 6 6-6 6"/></svg></button>
      </nav>` : ""}
    </div>
    ${row?.reason ? `<div class="claim-relation-reason" data-kind="${selected}">${claimRelationSvgs[selected]}<span><strong>${reasonLabels[selected]}</strong>${escapeHtml(row.reason)}</span></div>` : ""}
    <div class="claim-comparison-layout">
      <section class="claim-comparison-origin" aria-label="当前观点">
        <p class="claim-comparison-label"><span class="claim-comparison-dot"></span>当前观点</p>
        ${renderClaimCard(normalizeKnowledgeClaim(payload.claim), { allowDelete: false, allowRelations: false, showSource: true, comparison: true })}
      </section>
      <section class="claim-comparison-related" aria-label="对照观点">
        <p class="claim-comparison-label">对照观点</p>
        ${row ? renderClaimCard(normalizeKnowledgeClaim(row.claim), { allowDelete: false, showSource: true, comparison: true, comparisonKind: selected })
          : '<p class="video-claims-notice" role="status">暂无关联观点</p>'}
      </section>
    </div>`;
  content.scrollTop = 0;
}

async function openClaimRelations(claimId, kind) {
  const dialog = document.querySelector("#claim-relations-dialog");
  const content = document.querySelector("#claim-relations-content");
  if (!dialog || !claimId) return;
  const requestId = ++claimRelationsRequestId;
  claimRelationsPayload = null;
  setClaimRelationMark(kind);
  content.setAttribute("aria-busy", "true");
  content.innerHTML = '<p class="video-claims-notice" role="status">正在加载关联观点…</p>';
  if (!dialog.open) dialog.showModal();
  content.scrollTop = 0;
  dialog.scrollTop = 0;
  try {
    const payload = await fetchApiJson(`/knowledge/claims/${encodeURIComponent(claimId)}/relations`);
    if (!dialog.open || requestId !== claimRelationsRequestId) return;
    claimRelationsPayload = payload;
    renderClaimRelations(kind);
    dialog.scrollTop = 0;
  } catch (error) {
    if (!dialog.open || requestId !== claimRelationsRequestId) return;
    content.innerHTML = `<div class="video-claims-notice" role="alert"><p>${error.status === 404 ? "该知识卡已移除" : "关联观点加载失败"}</p>${error.status === 404 ? "" : `<button class="primary-button small" type="button" data-claim-relations-id="${escapeAttr(claimId)}">重试</button>`}</div>`;
  } finally {
    if (requestId === claimRelationsRequestId) content.setAttribute("aria-busy", "false");
  }
}

function renderClaimCard(claim, { allowDelete = true, allowRelations = true, showSource = false, comparison = false, comparisonKind = "" } = {}) {
  const relationCounts = groupClaimRelationCounts(claim.relationCounts);
  const reasonItems = (Array.isArray(claim.reasons) ? claim.reasons : [claim.reasons])
    .filter((reason) => reason && String(reason).trim() && String(reason).trim() !== "未提及");
  const supplementary = [
    ["替代做法", claim.alternatives],
    ["价格信息", claim.priceInfo],
  ].filter(([, value]) => value && String(value).trim() !== "未提及");
  const tags = [...new Set([claim.stage, ...(claim.tags || [])].filter((tag) => tag && tag !== "未提及"))];
  const stance = getAuthorStancePresentation(claim.authorStance);
  const promotionNoticeId = claim.sourceVideoIsPromotional ? `claim-promotion-${++claimPromotionNoticeSequence}` : "";
  const hasConditions = claim.conditions && claim.conditions.trim() !== "未提及";
  const quotes = (claim.sourceQuotes || []).filter((quote) => typeof quote === "string" && quote.trim());
  const contentType = claim.contentType && claim.contentType !== "未分类" ? claim.contentType : "";
  const deleteButton =
    allowDelete && adminSession.authenticated && claim.id
      ? `<button class="primary-button small claim-delete-action" type="button" data-delete-claim-id="${escapeAttr(claim.id)}" data-delete-claim-video-id="${escapeAttr(claim.videoId || "")}" aria-label="删除观点：${escapeAttr(claim.object)}" title="删除观点">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 6h18M9 6V4h6v2M5 6l1 14h12l1-14M10 10v6M14 10v6"/></svg>
          <span>删除观点</span>
        </button>`
      : "";
  return `
    <article class="result-card claim-card" data-claim-id="${escapeAttr(claim.id || "")}">
      <header class="claim-card-heading">
        <h3>${escapeHtml(claim.object)}</h3>
        <div class="claim-card-badges">
          <span class="claim-author-stance" data-stance="${stance.state}">${videoBadgeSvg(stance.state)}<span>${stance.label}</span></span>
          ${promotionNoticeId ? `<span class="claim-promotion-notice">
            <button class="claim-promotion-toggle" type="button" aria-label="推广来源" aria-describedby="${promotionNoticeId}" aria-controls="${promotionNoticeId}" aria-expanded="false">${videoBadgeSvg("promotion")}</button>
            <span class="claim-promotion-tooltip" id="${promotionNoticeId}" role="tooltip" hidden>来源视频标记为推广</span>
          </span>` : ""}
        </div>
      </header>
      <section class="claim-conclusion" aria-label="来源观点">
        <p>${escapeHtml(claim.conclusion || "未提及")}</p>
      </section>
      ${hasConditions ? `<p class="claim-conditions"><span>适用条件</span>${escapeHtml(claim.conditions)}</p>` : ""}
      ${allowRelations && claim.id && !comparison ? `<div class="claim-relation-links">${Object.entries(claimRelationLabels)
        .filter(([kind]) => relationCounts[kind] > 0)
        .map(([kind, label]) => `<button type="button" data-claim-relations-id="${escapeAttr(claim.id)}" data-relation-kind="${kind}" aria-haspopup="dialog" aria-controls="claim-relations-dialog">${claimRelationSvgs[kind]}<span>${label}</span><span class="claim-relation-count">${relationCounts[kind]}</span></button>`).join("")}</div>` : ""}
      <details class="claim-more">
        <summary><span class="claim-more-closed">展开详情</span><span class="claim-more-open">收起详情</span></summary>
        <div class="claim-more-body">
          ${contentType ? `<div class="claim-context-meta"><span>${escapeHtml(contentType)}</span></div>` : ""}
          ${reasonItems.length ? `<section class="claim-reasons" aria-label="作者给出的理由">
            <span class="claim-field-label">理由</span>
            <ul>${reasonItems.map((reason) => `<li>${escapeHtml(reason)}</li>`).join("")}</ul>
          </section>` : ""}
          ${supplementary.length ? `<dl class="claim-supplementary">${supplementary.map(([label, value]) => `<div><dt>${label}</dt><dd>${escapeHtml(value)}</dd></div>`).join("")}</dl>` : ""}
          ${quotes.length ? `<section class="claim-evidence" aria-label="原文引句"><span class="claim-field-label">原文</span>${quotes.map((quote) => `<blockquote>${escapeHtml(quote)}</blockquote>`).join("")}</section>` : '<p class="claim-evidence-missing">暂无引句</p>'}
          ${tags.length > 1 ? `<div class="claim-card-tags" aria-label="全部分类">${tags.slice(1).map((tag) => `<span class="chip">${escapeHtml(tag)}</span>`).join("")}</div>` : ""}
        </div>
      </details>
      <footer class="claim-card-footer">
        ${showSource && (claim.creator || claim.videoTitle) ? `<p class="claim-comparison-source">${claim.creator ? `<span>${escapeHtml(claim.creator)}</span>` : ""}${claim.videoTitle ? `<span class="claim-comparison-video-title" title="${escapeAttr(claim.videoTitle)}">${escapeHtml(claim.videoTitle)}</span>` : ""}</p>` : ""}
        <div class="claim-card-actions">
          ${tags.length && !comparison ? `<span class="claim-stage-label">${escapeHtml(tags[0])}</span>` : ""}
          ${comparison && allowRelations && claim.id && Object.values(relationCounts).some(count => count > 0) ? `<button class="claim-comparison-follow" type="button" data-claim-relations-id="${escapeAttr(claim.id)}" data-relation-kind="${escapeAttr(comparisonKind)}" aria-haspopup="dialog" aria-controls="claim-relations-dialog" aria-label="继续对比：${escapeAttr(claim.object)}">${claimRelationSvgs[comparisonKind] || claimRelationSvgs.similar}<span>继续对比</span></button>` : ""}
          ${claim.videoId ? `<button class="primary-button small claim-source-action" type="button" data-video-id="${escapeAttr(claim.videoId)}" aria-label="查看来源：${escapeAttr(claim.object)}">
            <span>查看来源</span>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 12h14m-5-5 5 5-5 5"/></svg>
          </button>` : ""}
          ${deleteButton}
        </div>
      </footer>
    </article>
  `;
}

function setClaimPromotionNotice(notice, visible) {
  notice.querySelector(".claim-promotion-toggle").setAttribute("aria-expanded", String(visible));
  const tooltip = notice.querySelector(".claim-promotion-tooltip");
  tooltip.hidden = !visible;
  if (visible) {
    delete notice.dataset.placement;
    const visibleBottom = Math.min(window.innerHeight, notice.closest("dialog")?.getBoundingClientRect().bottom ?? Infinity);
    if (tooltip.getBoundingClientRect().bottom > visibleBottom - 8) notice.dataset.placement = "above";
  }
  if (!visible) delete notice.dataset.pinned;
}

document.addEventListener("pointerover", (event) => {
  if (event.pointerType === "touch") return;
  const notice = event.target.closest(".claim-promotion-notice");
  if (notice && !notice.contains(event.relatedTarget)) setClaimPromotionNotice(notice, true);
});

document.addEventListener("pointerout", (event) => {
  const notice = event.target.closest(".claim-promotion-notice");
  if (notice && !notice.contains(event.relatedTarget) && !notice.dataset.pinned
      && !notice.contains(document.activeElement)) setClaimPromotionNotice(notice, false);
});

document.addEventListener("focusin", (event) => {
  const notice = event.target.closest(".claim-promotion-notice");
  if (notice) setClaimPromotionNotice(notice, true);
});

document.addEventListener("focusout", (event) => {
  const notice = event.target.closest(".claim-promotion-notice");
  if (notice && !notice.contains(event.relatedTarget) && !notice.dataset.pinned
      && !notice.matches(":hover")) setClaimPromotionNotice(notice, false);
});

function getTranscriptEdit(videoId) {
  if (!transcriptEdits.has(videoId)) {
    transcriptEdits.set(videoId, { draft: null, editing: false, saving: false, message: "", type: "" });
  }
  return transcriptEdits.get(videoId);
}

function renderTranscriptEditor(video) {
  if (window.DECOR_PUBLIC_LIBRARY) return;
  const state = video ? getTranscriptEdit(video.id) : null;
  const editing = !isDeletedVideoDetail() && !video?.sourceReadOnly && Boolean(state?.editing);
  const transcription = videoTranscriptions.get(video?.id);
  const fetchButton = document.querySelector("#fetch-transcript");
  fetchButton.dataset.adminBlocked = String(!video?.detailLoaded || hasVideoTranscript(video) || editing || Boolean(videoExtractions.get(video?.id)?.running));
  fetchButton.dataset.adminBusy = String(Boolean(transcription?.running));
  fetchButton.textContent = transcription?.running ? "获取中…" : hasVideoTranscript(video) ? "文案已保存" : video?.transcriptJob?.provider === "local_asr" && video?.transcriptJob?.task_id ? "重试本地转写" : video?.transcriptJob?.task_id ? "续查文案" : "获取文案";
  const editor = document.querySelector("#transcript-editor");
  const editButton = document.querySelector("#edit-transcript");
  const saveButton = document.querySelector("#save-transcript");
  document.querySelector("#transcript-text").hidden = editing;
  document.querySelector("#transcript-edit-form").hidden = !editing;
  editButton.hidden = editing;
  editButton.dataset.adminBlocked = String(!video?.detailLoaded || Boolean(state?.saving || transcription?.running || videoExtractions.get(video?.id)?.running));
  saveButton.dataset.adminBlocked = String(!video?.detailLoaded || Boolean(state?.saving) || !state?.draft?.trim());
  saveButton.textContent = state?.saving ? "保存中…" : "保存文案";
  document.querySelector("#cancel-transcript-edit").disabled = Boolean(state?.saving);
  editor.readOnly = !adminSession.authenticated || Boolean(state?.saving);
  if (editing && editor.value !== state.draft) editor.value = state.draft || "";
  const message = document.querySelector("#transcript-edit-message");
  message.textContent = state?.message || transcription?.message || "";
  message.dataset.type = state?.type || transcription?.type || "";
  renderDetailExtraction(video);
  syncAdminActionButtons();
}

function renderDetailExtraction(video) {
  if (window.DECOR_PUBLIC_LIBRARY) return;
  const button = document.querySelector("#detail-extract-video");
  const message = document.querySelector("#detail-extract-message");
  const state = video ? videoExtractions.get(video.id) : null;
  const edit = video ? getTranscriptEdit(video.id) : null;
  button.dataset.extractVideoId = video?.id || "";
  button.dataset.adminBlocked = String(!video?.detailLoaded || !hasVideoTranscript(video) || Boolean(edit?.editing || edit?.saving || videoTranscriptions.get(video?.id)?.running));
  button.dataset.adminBusy = String(Boolean(state?.running));
  button.textContent = state?.running ? "提取中…" : video?.claimCount > 0 ? "重新提取观点" : "提取观点";
  message.textContent = state?.message || "";
  message.dataset.type = state?.type || "";
}

function startTranscriptEdit() {
  requireAdminAction();
  const video = findDetailVideo(selectedVideoId);
  if (!video?.detailLoaded || video.sourceReadOnly || isDeletedVideoDetail()) return;
  const state = getTranscriptEdit(video.id);
  if (state.draft === null) state.draft = video.transcript || "";
  state.editing = true;
  state.message = "";
  renderTranscriptEditor(video);
  document.querySelector("#transcript-editor").focus();
}

async function saveTranscriptEdit() {
  requireAdminAction();
  const video = findDetailVideo(selectedVideoId);
  if (!video?.detailLoaded || video.sourceReadOnly || isDeletedVideoDetail()) return;
  const state = getTranscriptEdit(video.id);
  if (!state.editing || state.saving || !state.draft?.trim()) return;
  state.saving = true;
  state.message = "";
  renderTranscriptEditor(video);
  try {
    const result = await postJson(`${API_BASE}/videos/${video.id}/transcript`, {
      transcript_text: state.draft,
      transcript_source: "manual",
    });
    const updated = normalizeApiVideo(result.video);
    const replace = (item) => item.id === video.id ? { ...item, ...updated, claims: item.claims, claimCount: item.claimCount } : item;
    videos = videos.map(replace);
    progressVideos = progressVideos.map(replace);
    state.editing = false;
    state.draft = null;
    state.message = `已保存 ${updated.transcriptLength} 字，现有知识卡保留；重新提取可更新。`;
    state.type = "ok";
    await Promise.allSettled([
      loadVideoDetail(video.id),
      fetchApiJson("/bootstrap").then((payload) => {
        apiStats = normalizeApiStats(payload.stats || {});
        sources = payload.sources || sources;
        videoFacets = payload.video_facets || videoFacets;
        knowledgeFacets = payload.knowledge?.facets || knowledgeFacets;
      }),
      loadProgressSummary(),
    ]);
    writeApiCache();
    renderAll();
  } catch (error) {
    state.message = `保存失败：${error.message}`;
    state.type = "error";
  } finally {
    state.saving = false;
    renderDetail();
  }
}

const promotionEdits = new Map();

function renderPromotionEditor(video) {
  const state = promotionEdits.get(video?.id);
  const review = video?.adReview;
  const manual = review?.source === "manual";
  const promotion = getPromotionPresentation(video);
  const badge = document.querySelector("#promotion-current");
  const decision = review?.decision;
  badge.innerHTML = `${videoBadgeSvg(promotion.icon)}<span>${promotion.label}</span>`;
  badge.dataset.state = promotion.state;
  badge.title = decision ? window.DECOR_PUBLIC_LIBRARY ? promotion.label : manual ? "手动设置，优先于自动识别" : "自动识别" : "尚未识别推广状态";
  badge.hidden = !video;
  if (window.DECOR_PUBLIC_LIBRARY) return;
  const editor = document.querySelector("#promotion-editor");
  // data-video-id is reserved for delegated navigation actions.
  if (editor.dataset.contextVideoId !== (video?.id || "") || !adminSession.authenticated || isDeletedVideoDetail()) editor.open = false;
  editor.dataset.contextVideoId = video?.id || "";
  editor.hidden = isDeletedVideoDetail() || video?.sourceReadOnly || !adminSession.authenticated || !video?.detailLoaded;
  const select = document.querySelector("#promotion-decision");
  select.value = state?.draft ?? (manual ? review.decision : "auto");
  select.disabled = !adminSession.authenticated || !video?.detailLoaded || Boolean(state?.saving);
  const button = document.querySelector("#save-promotion");
  button.dataset.adminBlocked = String(!video?.detailLoaded);
  button.dataset.adminBusy = String(Boolean(state?.saving));
  button.textContent = state?.saving ? "保存中…" : "保存";
  document.querySelector("#promotion-message").textContent = state?.message || "";
  select.title = manual ? "手动设置优先于自动识别" : "自动识别优先使用有效缓存；无缓存时，下次获取或保存文案后识别";
}

async function savePromotionEdit(event) {
  event.preventDefault();
  requireAdminAction();
  const video = findDetailVideo(selectedVideoId);
  if (!video?.detailLoaded || video.sourceReadOnly || isDeletedVideoDetail() || promotionEdits.get(video.id)?.saving) return;
  const decision = document.querySelector("#promotion-decision").value;
  const state = { draft: decision, saving: true, message: "" };
  promotionEdits.set(video.id, state);
  renderDetail();
  let saved = false;
  try {
    await postJson(`${API_BASE}/videos/${video.id}/promotion`, { decision });
    saved = true;
    state.draft = null;
    await loadApiData();
    await Promise.all([loadVideoDetail(video.id), loadKnowledgePage(), loadProgressSummary(), loadProgressPage()]);
    state.message = decision === "auto" ? "已恢复自动识别；无缓存时，下次获取或保存文案后识别。" : "已保存，优先于自动识别。";
    const editor = document.querySelector("#promotion-editor");
    if (editor.dataset.contextVideoId === video.id) editor.open = false;
  } catch (error) {
    state.message = `${saved ? "状态已保存，但刷新失败，请刷新页面" : "保存失败"}：${error.message}`;
  } finally {
    state.saving = false;
    renderAll();
  }
}

document.querySelector("#promotion-form")?.addEventListener("submit", savePromotionEdit);
document.querySelector("#promotion-decision")?.addEventListener("change", (event) => {
  if (selectedVideoId) promotionEdits.set(selectedVideoId, { draft: event.target.value, saving: false, message: "" });
});

document.addEventListener("click", (event) => {
  const editor = document.querySelector("#promotion-editor");
  if (editor?.open && !editor.contains(event.target)) editor.open = false;
});

function renderDetailSourceInfo(video) {
  const info = document.querySelector("#detail-source-info");
  const review = video?.adReview;
  const quotes = (review?.evidence || []).filter(quote => typeof quote === "string" && quote.trim());
  const content = video ? [
    video.shareUrl && video.shareUrl !== video.sourceUrl ? `<div><span>分享链接</span><a href="${safeUrl(video.shareUrl)}" target="_blank" rel="noreferrer">${escapeHtml(video.shareUrl)}</a></div>` : "",
    video.shareText ? `<div><span>分享文本</span><p>${escapeHtml(video.shareText)}</p></div>` : "",
    review?.reason ? `<div><span>${review.source === "manual" ? "标记说明" : "识别理由"}</span><p>${escapeHtml(String(review.reason).replaceAll("广告", "推广"))}</p></div>` : "",
    quotes.length ? `<div><span>识别依据</span><section>${quotes.map(quote => `<blockquote>${escapeHtml(quote)}</blockquote>`).join("")}</section></div>` : "",
  ].filter(Boolean).join("") : "";
  if (info.dataset.contextVideoId !== (video?.id || "")) info.open = false;
  info.dataset.contextVideoId = video?.id || "";
  info.hidden = !content;
  document.querySelector("#detail-source-content").innerHTML = content;
  const note = document.querySelector("#detail-processing-note");
  const busy = videoExtractions.get(video?.id)?.running || videoTranscriptions.get(video?.id)?.running;
  const notice = video?.lastError && !busy ? getProgressNotice({ ...video, adReview: null }) : null;
  if (note.dataset.contextVideoId !== (video?.id || "")) note.open = false;
  note.dataset.contextVideoId = video?.id || "";
  note.hidden = !notice;
  document.querySelector("#detail-processing-summary").textContent = notice?.summary || "";
  document.querySelector("#detail-processing-reason").textContent = notice?.detail || "";
}

function renderDetail() {
  const video = findDetailVideo(selectedVideoId);
  const deletedPreview = isDeletedVideoDetail() || Boolean(video?.sourceReadOnly);
  document.querySelector("#detail-view").dataset.deletedPreview = String(deletedPreview);
  const backLabel = document.querySelector("#back-to-videos span:last-child");
  backLabel.textContent = history.state?.returnView === "deleted" ? "返回回收站" : history.state?.returnView === "knowledge" ? "返回知识库" : history.state?.returnView === "progress" ? "返回处理进度" : history.state?.returnView === "sources" ? "返回视频来源" : "返回视频列表";
  document.querySelector("#detail-link").hidden = !video;
  renderPromotionEditor(video);
  renderTranscriptEditor(video);
  renderDetailSourceInfo(video);
  const detailActions = document.querySelector(".detail-actions");
  if (!video) {
    document.querySelector("#detail-platform").textContent = "暂无视频";
    document.querySelector("#detail-heading").textContent = detailLoadError ? "来源视频暂不可用" : detailLoadingId ? "正在加载来源视频…" : "暂无视频详情";
    document.querySelector("#detail-heading").removeAttribute("title");
    document.querySelector("#detail-creator").textContent = "-";
    document.querySelector("#detail-claim-count").textContent = "0";
    document.querySelector("#detail-status").replaceChildren();
    document.querySelector("#detail-published").textContent = "";
    document.querySelector("#detail-transcript-count").textContent = "";
    document.querySelector("#detail-link").href = "#";
    document.querySelector("#transcript-text").textContent = "暂无文案";
    document.querySelector("#video-claims").innerHTML = `<article class="result-card"><h3>${detailLoadError ? "详情加载失败" : detailLoadingId ? "正在加载…" : "暂无观点"}</h3>${detailLoadError ? `<p>${escapeHtml(detailLoadError)}</p><button type="button" class="primary-button small" data-retry-detail>重试加载</button>` : ""}</article>`;
    detailActions?.querySelector("[data-detail-delete-video]")?.remove();
    return;
  }
  detailActions?.querySelector("[data-detail-delete-video]")?.remove();
  if (adminSession.authenticated && !deletedPreview) {
    detailActions?.insertAdjacentHTML(
      "beforeend",
      `<button class="primary-button small red" type="button" data-detail-delete-video data-delete-video-id="${escapeAttr(video.id)}">删除视频</button>`,
    );
  }
  document.querySelector("#detail-platform").textContent = video.platform;
  document.querySelector("#detail-heading").textContent = video.title;
  document.querySelector("#detail-heading").title = video.title;
  document.querySelector("#detail-creator").textContent = video.creator;
  document.querySelector("#detail-published").textContent = video.publishTime === "未提及" ? "" : String(video.publishTime).replace("T", " ").replace(/(\d{2}:\d{2}):\d{2}.*$/, "$1");
  document.querySelector("#detail-claim-count").textContent = video.claims.length;
  const stages = getProgressStageTags(video).tags;
  document.querySelector("#detail-status").innerHTML = stages.filter(tag => tag.key !== "link")
    .map(tag => renderVideoStateBadge(tag.key === "transcript" ? "document" : "claims", tag.title, tag.state === "todo" ? "pending" : tag.state, `${tag.title}：${tag.label}`)).join("");
  if (deletedPreview) document.querySelector("#detail-status").insertAdjacentHTML("afterbegin", `<span class="video-state-badge" data-state="promotion">${videoBadgeSvg("delete")}<span>回收站</span></span>`);
  document.querySelector("#detail-link").href = sanitizeUrl(video.sourceUrl || video.shareUrl);
  document.querySelector("#detail-link").hidden = sanitizeUrl(video.sourceUrl || video.shareUrl) === "#";
  const hasFullTranscript = video.detailLoaded && Boolean(video.transcript?.trim());
  const transcriptFallback = "暂无文案";
  document.querySelector("#detail-transcript-count").textContent = video.transcriptLength ? `${video.transcriptLength} 字` : "";
  document.querySelector("#transcript-text").textContent = hasFullTranscript ? video.transcript : transcriptFallback;
  document.querySelector("#video-claims").innerHTML = video.claims.length
    ? video.claims
        .map((claim) =>
          renderClaimCard({
            ...claim,
            videoId: video.id,
            sourceUrl: video.sourceUrl,
          }, { allowDelete: !deletedPreview }),
        )
        .join("")
    : renderEmptyClaimsState(video);
  if (detailLoadError) {
    document.querySelector("#video-claims").insertAdjacentHTML("afterbegin", `<article class="result-card" role="alert"><h3>详情刷新失败</h3><p>${escapeHtml(detailLoadError)}</p><button type="button" class="primary-button small" data-retry-detail>重试加载</button></article>`);
  }
}

function renderEmptyClaimsState(video) {
  if (video.status === "claims_filtered") {
    return `<article class="result-card claim-empty-card"><h3>无可用观点</h3></article>`;
  }
  if (video.status === "transcript_failed") {
    return `<article class="result-card claim-empty-card"><h3>文案处理失败</h3></article>`;
  }
  if (video.lastError) {
    return `<article class="result-card claim-empty-card"><h3>观点提取未完成</h3></article>`;
  }
  return `<article class="result-card claim-empty-card"><h3>暂无知识卡</h3></article>`;
}

function claimMatchesKnowledgeCategory(claim, category) {
  if (!category || category.type === "all") return true;
  if (category.type === "stage") return claim.stage === category.value;
  if (category.type === "stageGroup") return category.stages.includes(claim.stage);
  if (category.type === "tag") return claim.tags.includes(category.value) || claim.stage.includes(category.value);
  if (category.type === "stance") return claim.stance === category.value;
  if (category.type === "authorStance") return claim.authorStance === category.value;
  if (category.type === "contentType") return claim.contentType === category.value;
  return true;
}

function getKnowledgeCategoryKey(category) {
  return `${category.type}:${category.value}`;
}

function getActiveKnowledgeCategoryKey() {
  return getKnowledgeCategoryKey(activeKnowledgeCategory);
}

function findKnowledgeCategory(type, value) {
  return knowledgeCategoryGroups.flatMap((group) => group.items).find((item) => item.type === type && item.value === value);
}

function getKnowledgeCategoryCount(category) {
  if (!knowledgeFacets) return null;
  if (!category || category.type === "all") return normalizeCount(knowledgeFacets.total) ?? 0;
  if (category.type === "stageGroup") {
    return category.stages.reduce((sum, stage) => sum + (normalizeCount(knowledgeFacets.stages[stage]) ?? 0), 0);
  }
  const counts = category.type === "stage" ? knowledgeFacets.stages : category.type === "stance" ? knowledgeFacets.stances
    : category.type === "authorStance" ? knowledgeFacets.author_stances : category.type === "contentType" ? knowledgeFacets.content_types : knowledgeFacets.tags;
  return normalizeCount(counts?.[category.value] ?? (category.value === "未分类" ? counts?.["旧版未分类"] : undefined)) ?? 0;
}

function renderKnowledgeCategories() {
  const activeKey = getActiveKnowledgeCategoryKey();
  const activeGroup = knowledgeCategoryGroups.find((group) => group.title === activeKnowledgeGroupTitle) || knowledgeCategoryGroups[0];
  const groupTabs = knowledgeCategoryGroups
    .map(
      (group) => `
        <button class="knowledge-group-toggle ${group.title === activeGroup.title ? "active" : ""}" type="button" aria-pressed="${group.title === activeGroup.title}" data-knowledge-group="${escapeAttr(group.title)}">
          <span>${escapeHtml(group.title)}</span>
          <small>${group.items.length}</small>
        </button>
      `,
    )
    .join("");
  const categoryTabs = activeGroup.items
    .map((item) => {
      const count = getKnowledgeCategoryCount(item) ?? "…";
      const key = getKnowledgeCategoryKey(item);
      return `
        <button class="stage-button ${activeKey === key ? "active" : ""}" type="button" aria-pressed="${activeKey === key}" data-knowledge-category-type="${escapeAttr(item.type)}" data-knowledge-category-value="${escapeAttr(item.value)}">
          <span class="category-label">${escapeHtml(item.label)}</span>
          <span class="category-count">${count}</span>
        </button>
      `;
    })
    .join("");
  document.querySelector("#knowledge-group-list").innerHTML = groupTabs;
  document.querySelector("#knowledge-stage-list").innerHTML = categoryTabs;
}

function renderKnowledge() {
  const claims = knowledgeClaims;
  const openClaims = new Set(activeView === "knowledge"
    ? navigationPositions.get(navigationEntryKey)?.openClaims || [] : []);

  document.querySelector("#knowledge-results").innerHTML =
    claims.length > 0
      ? `${claims.map(renderClaimCard).join("")}
        <article class="video-filter-notice">
          <span>已显示 ${claims.length} / ${knowledgePageState.total} 条观点</span>
          ${
            knowledgePageState.error
              ? `<span>加载失败：${escapeHtml(knowledgePageState.error)}</span>`
              : knowledgePageState.loading
                ? `<span>正在加载...</span>`
                : knowledgePageState.hasMore
                  ? `<button class="primary-button small" type="button" id="load-more-knowledge">加载更多</button>`
                  : `<span>已加载全部</span>`
          }
        </article>`
      : `<article class="result-card"><h3>${knowledgePageState.loading ? "正在加载观点…" : "暂无匹配观点"}</h3>${
          knowledgePageState.error ? `<p>${escapeHtml(knowledgePageState.error)}</p>` : ""
        }</article>`;
  document.querySelectorAll("#knowledge-results .claim-more").forEach((element) => {
    element.open = openClaims.has(element.closest("[data-claim-id]")?.dataset.claimId);
  });
  if (activeView === "knowledge" && claims.length && pendingKnowledgeReturnPosition) {
    restoreNavigationPosition(pendingKnowledgeReturnPosition);
    pendingKnowledgeReturnPosition = null;
  }
  renderKnowledgeCategories();
  setupAutoLoadMore();
}

function renderDeleted() {
  const container = document.querySelector("#deleted-list");
  if (!container) return;
  document.querySelectorAll("[data-deleted-tab]").forEach((button) => {
    const selected = button.dataset.deletedTab === activeDeletedTab;
    const videoTab = button.dataset.deletedTab === "videos";
    button.classList.toggle("active", selected);
    button.setAttribute("aria-selected", String(selected));
    button.tabIndex = selected ? 0 : -1;
    button.innerHTML = `${videoBadgeSvg(videoTab ? "video" : "claims")}<span>${videoTab ? "视频" : "知识卡"}</span><span class="deleted-tab-count">${videoTab ? deletedItems.videoTotal : deletedItems.claimTotal}</span>`;
    if (selected) container.setAttribute("aria-labelledby", button.id);
  });
  container.setAttribute("aria-busy", String(deletedItems.loading));
  if (!adminSession.authenticated) {
    container.innerHTML = `
      <article class="result-card">
        <h3>需要管理员登录</h3>
        <footer><button class="primary-button small red" type="button" id="admin-login-button-inline">管理员登录</button></footer>
      </article>
    `;
    return;
  }
  if (deletedItems.loading && !deletedItems.loaded) {
    container.innerHTML = `<article class="result-card"><h3>正在加载…</h3></article>`;
    return;
  }
  if (deletedItems.error && !deletedItems.loaded) {
    container.innerHTML = `<article class="result-card"><h3>加载失败</h3><p>${escapeHtml(deletedItems.error)}</p></article>`;
    return;
  }
  const videoCards = (activeDeletedTab === "videos" ? deletedItems.videos : [])
    .map(
      (video) => `
        <article class="video-card" data-deleted-item-id="${escapeAttr(video.id)}">
          <span class="status failed">回收站视频</span>
          <h3>${escapeHtml(video.title || video.id)}</h3>
          <p>${escapeHtml(video.creator || "未记录")} / ${escapeHtml(video.platform || "未记录")}</p>
          <div class="timeline-meta">
            <span class="chip">移入时间：${escapeHtml(formatEpochDateTime(video.deleted_at))}</span>
            <span class="chip">${escapeHtml(video.delete_reason || "未记录原因")}</span>
          </div>
          <footer>
            <button class="primary-button small red" type="button" data-restore-video-id="${escapeAttr(video.id)}">恢复视频</button>
            <button class="primary-button small" type="button" data-video-id="${escapeAttr(video.id)}" data-video-deleted="true">查看来源</button>
            <button class="primary-button small trash-purge-action" type="button" data-purge-video-id="${escapeAttr(video.id)}">永久删除</button>
          </footer>
        </article>
      `,
    )
    .join("");
  const claimCards = (activeDeletedTab === "claims" ? deletedItems.claims : [])
    .map(
      (claim) => `
        <article class="result-card claim-card" data-deleted-item-id="${escapeAttr(claim.id)}">
          <span class="status failed">回收站知识卡</span>
          <h3>${escapeHtml(claim.object_name || claim.id)}</h3>
          <p><strong>来源视频：</strong>${escapeHtml(claim.video_title || claim.video_id || "未记录")}</p>
          <p><strong>观点：</strong>${escapeHtml(claim.original_conclusion || "未提及")}</p>
          <footer class="timeline-meta">
            <span class="chip">移入时间：${escapeHtml(formatEpochDateTime(claim.deleted_at))}</span>
            <span class="chip">${claim.video_deleted_at ? "需先恢复视频" : "可恢复"}</span>
            <button class="primary-button small red" type="button" data-restore-claim-id="${escapeAttr(claim.id)}" ${claim.video_deleted_at ? "disabled" : ""}>恢复知识卡</button>
            ${claim.video_id ? `<button class="primary-button small" type="button" data-video-id="${escapeAttr(claim.video_id)}" data-video-deleted="${Boolean(claim.video_deleted_at)}">查看来源</button>` : ""}
          </footer>
        </article>
      `,
    )
    .join("");
  const hasDeletedItems = Boolean(videoCards || claimCards);
  const loadedCount = deletedItems[activeDeletedTab].length;
  const total = activeDeletedTab === "videos" ? deletedItems.videoTotal : deletedItems.claimTotal;
  container.innerHTML = hasDeletedItems
    ? `
        ${videoCards}
        ${claimCards}
        ${deletedItems.error ? `<article class="video-filter-notice" role="alert">${escapeHtml(deletedItems.error)}</article>` : ""}
        ${loadedCount < total ? `<article class="video-filter-notice deleted-pagination"><span>已显示 ${loadedCount} / ${total}</span><button class="primary-button small" type="button" data-load-more-deleted ${deletedItems.loading ? "disabled" : ""}>${deletedItems.loading ? "加载中…" : "加载更多"}</button></article>` : ""}
      `
    : `<article class="result-card"><h3>回收站暂无${activeDeletedTab === "videos" ? "视频" : "知识卡"}</h3></article>`;
}

function renderSettings() {
  const root = document.querySelector("#transcript-settings");
  if (!root) return;
  const state = transcriptSettings;
  const blocked = state.busy || state.loading || !state.provider;
  const label = state.provider === "local_asr" ? "本地 ASR" : state.provider === "transcriptgenerate" ? "API 转写" : "读取中…";
  root.setAttribute("aria-busy", String(state.busy || state.loading));
  root.innerHTML = `
    <div class="settings-current"><span>当前方式</span><strong>${label}</strong></div>
    <div class="transcript-provider-grid">
      <article class="transcript-provider-card ${state.provider === "transcriptgenerate" ? "selected" : ""}">
        <h3>API 转写</h3>
        <p>使用已配置的转写接口，消耗账号额度。</p>
        <button class="primary-button" data-select-transcript-provider="transcriptgenerate" ${adminActionAttributes(blocked || state.provider === "transcriptgenerate")}>${state.provider === "transcriptgenerate" ? "当前已启用" : "切换为 API"}</button>
      </article>
      <article class="transcript-provider-card ${state.provider === "local_asr" ? "selected" : ""}">
        <h3>本地 ASR</h3>
        <p>使用本机 CPU，检测通过后切换。</p>
        <button class="primary-button" data-select-transcript-provider="local_asr" ${adminActionAttributes(blocked || state.provider === "local_asr")}>${state.provider === "local_asr" ? "当前已启用" : "检测并切换为本地"}</button>
      </article>
    </div>
    <div class="local-asr-health" data-status="${escapeAttr(state.health?.status || "unknown")}">
      <div><strong>本地服务状态</strong><p>${escapeHtml(state.health?.message || "尚未检测，服务按需启动。")}</p></div>
      <button class="primary-button small" id="check-local-asr" ${adminActionAttributes(state.busy || state.loading)}>${state.busy ? "处理中…" : "检测本地服务"}</button>
    </div>
    <p class="settings-feedback" id="transcript-settings-message" role="status" data-error="${Boolean(state.error)}">${escapeHtml(state.error || state.message)}</p>
    <p class="settings-note">本地检测不验证抖音登录或下载权限，也不调用外部转写。切换前需核对未完成的 API 任务，避免重复提交。</p>
  `;
}

async function loadTranscriptSettings() {
  if (transcriptSettings.busy) return;
  const request = ++transcriptSettingsRequest;
  transcriptSettings.loading = true;
  renderSettings();
  try {
    const result = await fetchApiJson("/settings/transcription");
    if (request !== transcriptSettingsRequest) return;
    transcriptSettings.provider = result.provider;
    transcriptSettings.error = "";
  } catch (error) {
    if (request !== transcriptSettingsRequest) return;
    transcriptSettings.error = `读取设置失败：${error.message}`;
  } finally {
    if (request === transcriptSettingsRequest) {
      transcriptSettings.loading = false;
      renderSettings();
    }
  }
}

async function updateTranscriptSettings(provider = null) {
  if (transcriptSettings.busy || transcriptSettings.loading) return;
  try { requireAdminAction(); } catch (error) {
    transcriptSettings.error = error.message;
    renderSettings();
    return;
  }
  ++transcriptSettingsRequest;
  transcriptSettings.busy = true;
  transcriptSettings.error = "";
  transcriptSettings.message = provider === "transcriptgenerate" ? "正在保存 API 转写方式…" : "正在检测本地 ASR 模型及实际推理，请稍候…";
  renderSettings();
  try {
    const path = provider ? "/settings/transcription" : "/settings/transcription/check-local";
    const response = await fetch(`${API_BASE}${path}`, {
      method: "POST", credentials: "include", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(provider ? { provider } : {}),
    });
    const result = await response.json();
    if (result.local_health) transcriptSettings.health = result.local_health;
    if (!provider && "ready" in result) transcriptSettings.health = result;
    if (result.provider) transcriptSettings.provider = result.provider;
    if (!response.ok) throw new Error(result.error || result.local_health?.message || result.message || "操作失败，原设置保持不变。");
    transcriptSettings.message = provider ? "转写方式已保存，后续任务立即生效。" : result.message;
  } catch (error) {
    transcriptSettings.error = error.message;
    transcriptSettings.message = "";
  } finally {
    transcriptSettings.busy = false;
    renderSettings();
  }
}

function renderCurrentView() {
  if (activeView === "overview") {
    renderOverview();
  } else if (activeView === "sources") {
    renderSources();
  } else if (activeView === "videos") {
    renderVideos();
  } else if (activeView === "progress") {
    renderProgress();
  } else if (activeView === "detail") {
    renderDetail();
  } else if (activeView === "knowledge") {
    renderKnowledge();
  } else if (activeView === "guide") {
    window.DecorGuides?.render();
  } else if (activeView === "deleted") {
    renderDeleted();
  } else if (activeView === "settings") {
    renderSettings();

  }
}

function renderIfActive(...views) {
  if (views.includes(activeView)) {
    renderCurrentView();
  }
}

document.addEventListener("click", (event) => {
  const promotionNotice = event.target.closest(".claim-promotion-notice");
  document.querySelectorAll('.claim-promotion-notice:has([aria-expanded="true"])').forEach((notice) => {
    if (notice !== promotionNotice) setClaimPromotionNotice(notice, false);
  });
  if (event.target.closest(".claim-promotion-toggle")) {
    const pinned = !promotionNotice.dataset.pinned;
    setClaimPromotionNotice(promotionNotice, pinned);
    if (pinned) promotionNotice.dataset.pinned = "true";
    return;
  }
  const copySourceButton = event.target.closest("[data-copy-source-url]");
  if (copySourceButton) {
    if (!copySourceButton.disabled) copySourceLink(copySourceButton);
    return;
  }
  const adminAction = event.target.closest("[data-admin-required]");
  if (adminAction && (!adminSession.authenticated || adminAction.disabled)) {
    event.preventDefault();
    return;
  }
  const editTranscriptButton = event.target.closest("#edit-transcript");
  if (editTranscriptButton) {
    startTranscriptEdit();
    return;
  }
  const cancelTranscriptButton = event.target.closest("#cancel-transcript-edit");
  if (cancelTranscriptButton) {
    const video = findDetailVideo(selectedVideoId);
    if (video) {
      const state = getTranscriptEdit(video.id);
      state.editing = false;
      state.draft = null;
      state.message = "";
      renderDetail();
    }
    return;
  }
  const providerButton = event.target.closest("[data-select-transcript-provider]");
  if (providerButton) {
    if (!providerButton.disabled) updateTranscriptSettings(providerButton.dataset.selectTranscriptProvider);
    return;
  }
  const checkLocalButton = event.target.closest("#check-local-asr");
  if (checkLocalButton) {
    if (!checkLocalButton.disabled) updateTranscriptSettings();
    return;
  }
  const navButton = event.target.closest(".nav-item");
  if (navButton) {
    setView(navButton.dataset.view);
    return;
  }

  const adminLogin = event.target.closest("#admin-login-button");
  if (adminLogin) {
    loginAdmin(adminLogin);
    return;
  }

  const adminLoginInline = event.target.closest("#admin-login-button-inline");
  if (adminLoginInline) {
    loginAdmin(adminLoginInline);
    return;
  }

  const adminLoginClose = event.target.closest("[data-admin-login-close]");
  if (adminLoginClose) {
    closeAdminLoginModal();
    return;
  }

  const adminLogout = event.target.closest("#admin-logout-button");
  if (adminLogout) {
    logoutAdmin();
    return;
  }

  const refreshDeletedButton = event.target.closest("#refresh-deleted");
  if (refreshDeletedButton) {
    refreshDeletedButton.disabled = true;
    loadDeletedItems().finally(() => {
      refreshDeletedButton.disabled = false;
    });
    return;
  }

  const deletedTab = event.target.closest("[data-deleted-tab]");
  if (deletedTab) {
    activeDeletedTab = deletedTab.dataset.deletedTab;
    renderDeleted();
    return;
  }

  if (event.target.closest("[data-load-more-deleted]")) {
    if (!deletedItems.loading) loadDeletedItems({ append: true });
    return;
  }

  const restoreVideoButton = event.target.closest("[data-restore-video-id]");
  if (restoreVideoButton) {
    restoreVideoButton.disabled = true;
    restoreVideo(restoreVideoButton.dataset.restoreVideoId)
      .catch((error) => alert(`恢复视频失败：${error.message}`))
      .finally(() => {
        restoreVideoButton.disabled = false;
      });
    return;
  }

  const purgeVideoButton = event.target.closest("[data-purge-video-id]");
  if (purgeVideoButton) {
    purgeVideo(purgeVideoButton.dataset.purgeVideoId).catch(error => alert(`永久删除失败：${error.message}`));
    return;
  }

  const restoreClaimButton = event.target.closest("[data-restore-claim-id]");
  if (restoreClaimButton) {
    restoreClaimButton.disabled = true;
    restoreClaim(restoreClaimButton.dataset.restoreClaimId)
      .catch((error) => alert(`恢复观点失败：${error.message}`))
      .finally(() => {
        restoreClaimButton.disabled = false;
      });
    return;
  }

  const deleteVideoButton = event.target.closest("[data-delete-video-id]");
  if (deleteVideoButton) {
    event.preventDefault();
    deleteVideo(deleteVideoButton.dataset.deleteVideoId).catch((error) => alert(`删除视频失败：${error.message}`));
    return;
  }

  const deleteClaimButton = event.target.closest("[data-delete-claim-id]");
  if (deleteClaimButton) {
    event.preventDefault();
    deleteClaim(deleteClaimButton.dataset.deleteClaimId, deleteClaimButton.dataset.deleteClaimVideoId).catch((error) =>
      alert(`删除观点失败：${error.message}`),
    );
    return;
  }

  const videoClaimsButton = event.target.closest("[data-video-claims-id]");
  if (videoClaimsButton) {
    openVideoClaims(videoClaimsButton.dataset.videoClaimsId);
    return;
  }

  const claimRelationsButton = event.target.closest("[data-claim-relations-id]");
  if (claimRelationsButton) {
    openClaimRelations(claimRelationsButton.dataset.claimRelationsId, claimRelationsButton.dataset.relationKind);
    return;
  }
  const claimRelationTab = event.target.closest("[data-claim-relation-tab]");
  if (claimRelationTab) {
    renderClaimRelations(claimRelationTab.dataset.claimRelationTab);
    document.querySelector(`[data-claim-relation-tab="${claimRelationTab.dataset.claimRelationTab}"]`)?.focus({ preventScroll: true });
    return;
  }
  const claimRelationStep = event.target.closest("[data-claim-relation-step]");
  if (claimRelationStep) {
    const step = claimRelationStep.dataset.claimRelationStep;
    renderClaimRelations(claimRelationsKind, claimRelationsIndex + Number(step));
    const pager = document.querySelector(".claim-comparison-pager");
    const nextFocus = pager?.querySelector(`[data-claim-relation-step="${step}"]:not(:disabled)`)
      || pager?.querySelector("button:not(:disabled)");
    nextFocus?.focus({ preventScroll: true });
    return;
  }

  const exclusionsButton = event.target.closest("[data-video-exclusions-id]");
  if (exclusionsButton) {
    openVideoExclusions(exclusionsButton.dataset.videoExclusionsId);
    return;
  }

  const videoButton = event.target.closest("[data-video-id]");
  if (videoButton) {
    event.preventDefault();
    document.querySelector("#video-claims-dialog")?.close();
    document.querySelector("#claim-relations-dialog")?.close();
    if (activeView === "detail" && selectedVideoId === videoButton.dataset.videoId) {
      document.querySelector("#detail-heading").scrollIntoView({ block: "start", behavior: "smooth" });
      return;
    }
    const returnView = activeView;
    selectedVideoId = videoButton.dataset.videoId;
    setView("detail", { returnView, deletedVideo: videoButton.dataset.videoDeleted === "true" });
    loadSelectedVideoDetail();
    return;
  }

  if (event.target.closest("[data-retry-detail]")) {
    loadSelectedVideoDetail();
    return;
  }

  const backToVideosButton = event.target.closest("#back-to-videos");
  if (backToVideosButton) {
    if (history.state?.returnView && navigationPositions.has(history.state.returnEntryKey)) history.back();
    else setView(history.state?.returnView || (isDeletedVideoDetail() ? "deleted" : "videos"));
    return;
  }

  const stageButton = event.target.closest(".timeline-card[data-knowledge-stage], [data-knowledge-stage]");
  if (stageButton) {
    const stageName = stageButton.dataset.knowledgeStage;
    activeKnowledgeCategory = { type: "stage", value: stageName, label: stageName };
    activeKnowledgeGroupTitle = "按装修阶段";
    loadKnowledgePage();
    setView("knowledge");
    return;
  }

  const knowledgeGroupButton = event.target.closest("[data-knowledge-group]");
  if (knowledgeGroupButton) {
    const groupTitle = knowledgeGroupButton.dataset.knowledgeGroup;
    activeKnowledgeGroupTitle = groupTitle;
    activeKnowledgeCategory = knowledgeCategoryGroups.find((group) => group.title === groupTitle)?.items[0] || findKnowledgeCategory("all", "全部");
    renderKnowledgeCategories();
    document.querySelector("#knowledge-stage-list").scrollLeft = 0;
    loadKnowledgePage();
    return;
  }

  const categoryButton = event.target.closest("[data-knowledge-category-type]");
  if (categoryButton) {
    activeKnowledgeCategory =
      findKnowledgeCategory(categoryButton.dataset.knowledgeCategoryType, categoryButton.dataset.knowledgeCategoryValue) ||
      findKnowledgeCategory("all", "全部");
    loadKnowledgePage();
    return;
  }

  const progressFilterButton = event.target.closest("[data-progress-filter]");
  if (progressFilterButton) {
    activeProgressFilter = progressFilterButton.dataset.progressFilter;
    progressVideos = [];
    progressPageState = { ...progressPageState, offset: 0, hasMore: false, error: "" };
    loadProgressPage();
    return;
  }

  const videoPlatformButton = event.target.closest("[data-video-platform]");
  if (videoPlatformButton) {
    activeSourceFilter = null;
    activeVideoPlatform = videoPlatformButton.dataset.videoPlatform;
    activeVideoCreator = "全部";
    loadVideoPage();
    return;
  }

  const videoCreatorButton = event.target.closest("[data-video-creator]");
  if (videoCreatorButton) {
    activeSourceFilter = null;
    activeVideoCreator = videoCreatorButton.dataset.videoCreator;
    loadVideoPage();
    return;
  }

  const openIngestButton = event.target.closest("#open-ingest");
  if (openIngestButton) {
    if (openIngestButton.hidden) return;
    setIngestOpen(true);
    return;
  }

  const closeIngestButton = event.target.closest("#close-ingest, #cancel-ingest");
  if (closeIngestButton) {
    setIngestOpen(false);
    return;
  }

  const retryApiLoadButton = event.target.closest("#retry-api-load");
  if (retryApiLoadButton) {
    retryApiLoadButton.disabled = true;
    loadApiData({ attempt: 1 }).finally(() => {
      retryApiLoadButton.disabled = false;
    });
    return;
  }

  const updateSourceButton = event.target.closest("[data-update-source-id]");
  if (updateSourceButton) {
    setAdminActionBusy(updateSourceButton, true);
    updateSource(updateSourceButton.dataset.updateSourceId)
      .catch((error) => setSourceMessage(`失败：${error.message}`, "error"))
      .finally(() => {
        setAdminActionBusy(updateSourceButton, false);
      });
    return;
  }

  const checkDouyinLoginButton = event.target.closest("#check-douyin-login");
  if (checkDouyinLoginButton) {
    checkDouyinLoginButton.disabled = true;
    refreshDouyinLoginStatus()
      .then((status) => setSourceMessage(status.message || "登录态检查完成。", status.logged_in ? "ok" : "warn"))
      .catch((error) => setSourceMessage(`登录态检查失败：${error.message}`, "error"))
      .finally(() => {
        checkDouyinLoginButton.disabled = false;
      });
    return;
  }

  const douyinLoginButton = event.target.closest("[data-douyin-login-url]");
  if (douyinLoginButton) {
    setAdminActionBusy(douyinLoginButton, true);
    startDouyinLogin(douyinLoginButton.dataset.douyinLoginUrl)
      .catch((error) => setSourceMessage(`打开登录失败：${error.message}`, "error"))
      .finally(() => {
        setAdminActionBusy(douyinLoginButton, false);
      });
    return;
  }

  const updateAllSourcesButton = event.target.closest("#update-all-sources");
  if (updateAllSourcesButton) {
    setAdminActionBusy(updateAllSourcesButton, true);
    updateAllSources()
      .catch((error) => setSourceMessage(`失败：${error.message}`, "error"))
      .finally(() => {
        setAdminActionBusy(updateAllSourcesButton, false);
      });
    return;
  }

  const sourceFilterCard = event.target.closest("[data-source-filter-id]");
  if (sourceFilterCard) {
    const retryPerformance = event.target.closest("[data-retry-source-performance]");
    if (retryPerformance) { loadSourcePerformance(); return; }
    if (event.target.closest("button, a, details, summary, input, select, textarea")) return;
    applySourceFilter(sourceFilterCard.dataset.sourceFilterId, sourceFilterCard.dataset.sourceFilterName);
    return;
  }

  const clearSourceFilterButton = event.target.closest("#clear-source-filter");
  if (clearSourceFilterButton) {
    activeSourceFilter = null;
    loadVideoPage();
    return;
  }

  const retryVideoPageButton = event.target.closest("#retry-video-page");
  if (retryVideoPageButton) {
    retryVideoPageButton.disabled = true;
    loadVideoPage({ preserveLoaded: true });
    return;
  }

  const loadMoreVideosButton = event.target.closest("#load-more-videos");
  if (loadMoreVideosButton) {
    loadMoreVideosButton.disabled = true;
    loadVideoPage({ append: true });
    return;
  }

  const loadMoreKnowledgeButton = event.target.closest("#load-more-knowledge");
  if (loadMoreKnowledgeButton) {
    loadMoreKnowledgeButton.disabled = true;
    loadKnowledgePage({ append: true });
    return;
  }

  const loadMoreProgressButton = event.target.closest("#load-more-progress");
  if (loadMoreProgressButton) {
    loadMoreProgressButton.disabled = true;
    loadProgressPage({ append: true });
    return;
  }

  const progressRunButton = event.target.closest("#progress-process-pending");
  if (progressRunButton) {
    if (lastQueueStatus?.running) {
      cancelQueueJob().catch((error) => {
        setProgressRunButtonState("running", "暂停处理");
        setProgressMessage(`暂停失败：${error.message}`, "error");
      });
      return;
    }
    setProgressRunButtonState("starting", "启动中...");
    startQueueJob(5)
      .catch((error) => {
        setProgressRunButtonState("idle", "自动处理剩余");
        setProgressMessage(`自动处理失败：${error.message}`, "error");
      })
      .finally(() => {
        if (!lastQueueStatus?.running) {
          setProgressRunButtonState("idle", "自动处理剩余");
        }
      });
    return;
  }

  const logFollowButton = event.target.closest("[data-log-follow-bottom]");
  if (logFollowButton) {
    event.preventDefault();
    event.stopPropagation();
    jumpLogToBottom(logFollowButton.closest(".queue-log-panel"));
    return;
  }

  const closeRowLogButton = event.target.closest("[data-close-row-log]");
  if (closeRowLogButton) {
    event.preventDefault();
    activeProgressLogVideoId = null;
    queueLogMode = "global";
    lastQueueStatus = null;
    renderProgress();
    return;
  }

  const progressRetryButton = event.target.closest("[data-progress-retry-video-id]");
  if (progressRetryButton) {
    const state = progressRetryButton.dataset.progressRetryState;
    const videoId = progressRetryButton.dataset.progressRetryVideoId;
    const video = progressVideos.find((item) => item.id === videoId) || videos.find((item) => item.id === videoId);
    let force = false;
    const originalLabel = progressRetryButton.textContent;
    setAdminActionBusy(progressRetryButton, true);
    if (state === "缺链接") {
      setView("sources");
      setSourceMessage("这条视频缺链接，请先从来源页更新该博主作品。", "warn");
      setAdminActionBusy(progressRetryButton, false);
      return;
    }
    if ((video?.retryCount || 0) >= 3) {
      force = confirm(`该视频已重试 ${video.retryCount} 次，仍可能无法正确提取文案。确定继续从获取文案开始重试吗？`);
      if (!force) {
        setAdminActionBusy(progressRetryButton, false);
        return;
      }
    }
    progressRetryButton.textContent = "处理中";
    startVideoRetryJob(videoId, force)
      .catch((error) => {
        if (error.message.includes("retry_confirmation_required")) {
          setProgressMessage("该视频已重试 3 次，需要确认后再重试。", "warn");
          return;
        }
        setProgressMessage(`重试失败：${error.message}`, "error");
      })
      .finally(() => {
        setAdminActionBusy(progressRetryButton, false);
        progressRetryButton.textContent = originalLabel;
      });
    return;
  }

  const transcriptButton = event.target.closest("#fetch-transcript");
  if (transcriptButton) {
    requireAdminAction();
    const videoId = selectedVideoId;
    const video = findDetailVideo(videoId);
    if (!video?.detailLoaded || hasVideoTranscript(video) || videoTranscriptions.get(videoId)?.running) return;
    const state = { running: true, message: "正在获取文案…", type: "" };
    videoTranscriptions.set(videoId, state);
    getTranscriptEdit(videoId).message = "";
    renderDetail();
    postJson(`${API_BASE}/videos/${videoId}/transcript/retry`, {})
      .then(async () => {
        state.message = "文案已保存";
        state.type = "ok";
        await loadApiData();
        await loadVideoDetail(videoId);
      })
      .catch((error) => {
        state.message = `获取未完成：${error.message}`;
        state.type = "error";
        if (selectedVideoId !== videoId || activeView !== "detail") alert(state.message);
      })
      .finally(() => {
        state.running = false;
        renderIfActive("detail", "videos", "progress");
      });
    return;
  }

  const extractButton = event.target.closest("[data-extract-video-id]");
  if (extractButton) {
    const videoId = extractButton.dataset.extractVideoId;
    if (!videoId || videoExtractions.get(videoId)?.running) return;
    const state = { running: true, message: "正在提取观点…", type: "" };
    videoExtractions.set(videoId, state);
    renderIfActive("detail", "videos");
    setAdminActionBusy(extractButton, true);
    extractButton.textContent = "提取中";
    postJson(`${API_BASE}/videos/${videoId}/extract`, {})
      .then(async (result) => {
        if (!["completed", "filtered"].includes(result.status)) throw new Error(result.status || "extract_failed");
        state.message = result.message || (result.status === "filtered" ? "本次未收录观点，已保留原文案。" : `提取完成，保存 ${(result.claims || []).length} 条观点。`);
        state.type = "ok";
        await loadApiData();
        selectedVideoId = videoId;
        await loadVideoDetail(videoId);
        renderAll();
        renderDetail();
        renderProgress();
        setView("detail");
      })
      .catch((error) => {
        state.message = error.message.includes("deepseek_timeout") || error.message.includes("Operation timed out")
          ? "模型超时，文案和知识卡已保留，可重试。"
          : `提取失败：${error.message}`;
        state.type = "error";
        if (activeView !== "detail" || selectedVideoId !== videoId) alert(state.message);
      })
      .finally(() => {
        state.running = false;
        setAdminActionBusy(extractButton, false);
        renderIfActive("detail", "videos");
      });
  }
});

document.querySelector("#transcript-editor")?.addEventListener("input", (event) => {
  const video = findDetailVideo(selectedVideoId);
  if (!video) return;
  const state = getTranscriptEdit(video.id);
  state.draft = event.target.value;
  state.message = "";
  renderTranscriptEditor(video);
});

document.querySelector("#knowledge-query").addEventListener("input", () => {
  window.clearTimeout(knowledgeSearchTimer);
  knowledgeSearchTimer = window.setTimeout(() => loadKnowledgePage(), 250);
});
document.addEventListener("submit", (event) => {
  if (event.target.id === "transcript-edit-form") {
    event.preventDefault();
    saveTranscriptEdit().catch((error) => {
      const video = findDetailVideo(selectedVideoId);
      if (!video) return;
      const state = getTranscriptEdit(video.id);
      state.message = error.message;
      state.type = "error";
      renderTranscriptEditor(video);
    });
    return;
  }
  if (event.target === adminLoginForm) {
    event.preventDefault();
    submitAdminLogin(adminLoginPassword?.value);
    return;
  }
  if (event.target !== ingestForm) return;
  event.preventDefault();
  if (ingestSubmitting) return;
  ingestSubmitting = true;
  ingestForm.setAttribute("aria-busy", "true");
  const submitButton = ingestForm.querySelector("button[type='submit']");
  const submitLabel = submitButton.querySelector("[data-ingest-submit-label]");
  setAdminActionBusy(submitButton, true);
  submitLabel.textContent = "正在采集…";
  ingestPanel.querySelectorAll("#close-ingest, #cancel-ingest").forEach((button) => { button.disabled = true; });
  saveVideoFromForm(event.submitter?.dataset.mode || ingestSubmitMode).catch((error) => {
    setIngestMessage(`失败：${error.message}`, "error");
  }).finally(() => {
    ingestSubmitting = false;
    ingestForm.setAttribute("aria-busy", "false");
    setAdminActionBusy(submitButton, false);
    submitLabel.textContent = "保存并采集";
    ingestPanel.querySelectorAll("#close-ingest, #cancel-ingest").forEach((button) => { button.disabled = false; });
  });
});

adminLoginPassword?.addEventListener("input", () => {
  if (adminLoginMessage?.textContent) {
    setAdminLoginMessage();
  }
});

document.querySelectorAll("dialog").forEach((dialog) => {
  let startedOutside = false;
  const isOutside = (event) => {
    const rect = dialog.getBoundingClientRect();
    return event.clientX < rect.left || event.clientX > rect.right
      || event.clientY < rect.top || event.clientY > rect.bottom;
  };
  dialog.addEventListener("pointerdown", (event) => {
    startedOutside = event.button === 0 && event.target === dialog && isOutside(event);
  });
  dialog.addEventListener("pointercancel", () => { startedOutside = false; });
  dialog.addEventListener("close", () => { startedOutside = false; });
  dialog.addEventListener("click", (event) => {
    // Require both ends outside so selecting or dragging content never dismisses it.
    const dismiss = startedOutside && event.target === dialog && isOutside(event);
    startedOutside = false;
    if (dismiss) dialog.close("cancel");
  });
});

document.querySelector("#video-exclusions-dialog")?.addEventListener("close", (event) => {
  if (!event.target.open) clearVideoExclusions();
});

document.addEventListener("click", (event) => {
  const submitButton = event.target.closest("#ingest-form button[type='submit']");
  if (submitButton) {
    ingestSubmitMode = submitButton.dataset.mode || "save";
  }
});

document.addEventListener("toggle", (event) => {
  if (event.target.isConnected && event.target.matches(".progress-note[data-progress-note-id]")) {
    if (event.target.open) expandedProgressNotes.add(event.target.dataset.progressNoteId);
    else expandedProgressNotes.delete(event.target.dataset.progressNoteId);
  }
  if (event.target.isConnected && event.target.matches(".source-performance[data-source-performance]")) {
    const id = event.target.dataset.sourcePerformance;
    if (event.target.open) expandedSourcePerformance.add(id);
    else expandedSourcePerformance.delete(id);
  }
  // Keep reading state across late search responses without caching card content.
  if (activeView === "knowledge" && event.target.isConnected
      && event.target.matches("#knowledge-results .claim-more")) rememberNavigationPosition();
}, true);

document.addEventListener("keydown", (event) => {
  const deletedTab = event.target.closest("[data-deleted-tab]");
  if (deletedTab && ["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) {
    event.preventDefault();
    activeDeletedTab = event.key === "Home" ? "videos" : event.key === "End" ? "claims" : activeDeletedTab === "videos" ? "claims" : "videos";
    renderDeleted();
    document.querySelector(`[data-deleted-tab="${activeDeletedTab}"]`).focus();
    return;
  }
  if (event.key === "Escape") {
    const promotionNotices = document.querySelectorAll('.claim-promotion-notice:has([aria-expanded="true"])');
    if (promotionNotices.length) {
      event.preventDefault();
      promotionNotices.forEach((notice) => setClaimPromotionNotice(notice, false));
      return;
    }
  }
  if (event.key === "Escape" && adminLoginModal && !adminLoginModal.hidden) {
    event.preventDefault();
    closeAdminLoginModal();
    return;
  }
  const promotionEditor = document.querySelector("#promotion-editor");
  if (event.key === "Escape" && promotionEditor?.open) {
    event.preventDefault();
    promotionEditor.open = false;
    promotionEditor.querySelector("summary").focus();
    return;
  }
  if (event.key !== "Enter" && event.key !== " ") return;
  const sourceFilterCard = event.target.closest("[data-source-filter-id]");
  if (!sourceFilterCard || event.target.closest("button, a, details, summary, input, select, textarea")) return;
  event.preventDefault();
  applySourceFilter(sourceFilterCard.dataset.sourceFilterId, sourceFilterCard.dataset.sourceFilterName);
});

function renderAll() {
  renderCurrentView();
}

function updateKnowledgeBackToTop() {
  const button = document.querySelector("#knowledge-back-to-top");
  if (button) button.hidden = activeView !== "knowledge" || window.scrollY < 400;
}

window.addEventListener("scroll", updateKnowledgeBackToTop, { passive: true });
document.querySelector("#knowledge-back-to-top")?.addEventListener("click", () => {
  window.scrollTo({ top: 0, behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "instant" : "smooth" });
});

history.scrollRestoration = "manual";
navigationEntryKey = createNavigationEntryKey();
history.replaceState({ ...history.state, view: activeView, entryKey: navigationEntryKey }, "");
if (activeView === "detail" && history.state.videoId) selectedVideoId = history.state.videoId;
setView(activeView, { updateHash: false, render: false });
renderAdminSession();
renderCurrentView();
enforceHashView();
window.requestAnimationFrame(enforceHashView);
window.addEventListener("DOMContentLoaded", enforceHashView);
window.addEventListener("popstate", syncViewFromHash);
window.addEventListener("hashchange", syncViewFromHash);
loadAdminSession();
loadApiData();
