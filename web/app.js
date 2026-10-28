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
const API_CACHE_KEY = `zhuangxiuApiSnapshot:v6${window.DECOR_PUBLIC_LIBRARY ? `:${window.DECOR_PUBLIC_LIBRARY.snapshot}` : ""}`;
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
    title: "按态度",
    items: ["明确推荐", "明确不推荐", "有条件", "价格建议", "未明确"].map((value) => ({ type: "stance", value, label: value, meta: "观点态度" })),
  },
];
const viewTitles = {
  overview: "装修全流程知识地图",
  sources: "视频来源",
  videos: "视频列表",
  detail: "视频详情",
  progress: "处理进度",
  knowledge: "知识库",
  deleted: "已删除",
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
let activeView = getInitialView();
let selectedVideoId = videos[0]?.id || null;
const transcriptEdits = new Map();
const videoExtractions = new Map();
const videoTranscriptions = new Map();
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
let progressSummary = null;
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
    stage: claim.process_stage,
    tags: [...(claim.space_tags || []), ...(claim.topic_tags || [])].filter((tag) => tag && tag !== "未提及"),
    conclusion: claim.original_conclusion,
    reasons,
    conditions: claim.conditions,
    alternatives: alternatives || "未提及",
    priceInfo: claim.price_info,
    sourceUrl: claim.source_video_url,
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
    adReview: video.ad_review || null,
    publishTime: video.published_at || "未提及",
    createdAt: video.created_at || null,
    updatedAt: video.updated_at || null,
    transcriptCreatedAt: video.transcript_created_at || null,
    transcriptJob: video.transcript_job || null,
    lastRetryAt: video.last_retry_at || null,
    claimCount: video.claim_count || 0,
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

function renderAdBadge(video) {
  const decision = video.adReview?.decision;
  if (!decision || decision === "not_ad") return "";
  const label = decision === "advertising" ? "推广" : "疑似推广";
  return `<span class="status" title="${escapeAttr(getVideoReasonLabel(video))}">${label}</span>`;
}

function getVideoReasonLabel(video) {
  if (video?.adReview?.decision === "advertising") return `推广：${String(video.adReview.reason || "").replaceAll("广告", "推广")}；已跳过自动观点提取，可人工提取。`;
  if (["uncertain", "error"].includes(video?.adReview?.decision)) return `疑似推广：${String(video.adReview.reason || "").replaceAll("广告", "推广")}；暂不自动提取观点。`;
  const reason = String(video?.lastError || "").trim();
  if (!reason) return "";
  if (reason.startsWith("deepseek_timeout:") || reason.includes("Operation timed out")) {
    return "模型响应超时，文案和已有知识卡已保留，可稍后重试提取观点。";
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
  if (activeView === "detail" && snapshot.selectedVideoId) selectedVideoId = snapshot.selectedVideoId;
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
    if (ingestPanel) ingestPanel.hidden = true;
    openIngestButton?.setAttribute("aria-expanded", "false");
    if (["deleted", "settings"].includes(activeView)) setView(activeView);
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
}

async function loadAdminSession() {
  try {
    adminSession = await fetchApiJson("/admin/session");
  } catch (error) {
    adminSession = { authenticated: false, configured: false, error: error.message };
  }
  adminSessionLoaded = true;
  renderAdminSession();
  if (["#deleted", "#settings"].includes(window.location.hash)) syncViewFromHash();
  return adminSession;
}

async function loadDeletedItems() {
  if (!adminSession.authenticated) {
    deletedItems = { ...deletedItems, videos: [], claims: [], videoTotal: 0, claimTotal: 0, loading: false, error: "" };
    renderDeleted();
    return;
  }
  deletedItems = { ...deletedItems, loading: true, error: "" };
  renderDeleted();
  try {
    const payload = await fetchApiJson("/admin/deleted");
    deletedItems = {
      videos: payload.videos || [],
      claims: payload.claims || [],
      videoTotal: normalizeCount(payload.video_total) || 0,
      claimTotal: normalizeCount(payload.claim_total) || 0,
      loading: false,
      error: "",
    };
  } catch (error) {
    deletedItems = { ...deletedItems, loading: false, error: error.message };
  }
  renderDeleted();
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

function loadKnowledgePage({ append = false } = {}) {
  const requestId = ++knowledgeLoadRequestId;
  const offset = append ? knowledgePageState.offset : 0;
  if (!append) knowledgeClaims = [];
  knowledgePageState = { ...knowledgePageState, loading: true, error: "" };
  renderKnowledge();
  return fetchApiJson(`/knowledge${buildQueryString(getKnowledgeApiParams(offset))}`)
    .then((payload) => {
      if (requestId !== knowledgeLoadRequestId) return;
      const nextClaims = (payload.claims || []).map(normalizeKnowledgeClaim);
      knowledgeClaims = append ? appendUniqueById(knowledgeClaims, nextClaims) : nextClaims;
      updateKnowledgePageState(payload, append);
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
  if (!response.ok) throw new Error(`${path.replace(/^\//, "")} ${response.status}`);
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
    writeApiCache();
    if (bootstrapPayload.knowledge?.deferred) {
      loadKnowledgePage();
    }
    loadProgressSummary();
    loadProgressPage();
    if (activeView === "detail" && selectedVideoId) {
      loadVideoDetail(selectedVideoId).then(renderDetail).catch((error) => console.info("Video detail load failed:", error.message));
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
  const detail = await fetchApiJson(`/videos/${encodeURIComponent(videoId)}`);
  const detailedVideo = normalizeApiVideo({
    ...detail.video,
    claim_count: detail.claims.length,
    claims: detail.claims,
  });
  videos = upsertVideoById(videos, detailedVideo);
  progressVideos = upsertVideoById(progressVideos, detailedVideo);
  selectedVideoId = videoId;
  writeApiCache();
  return detailedVideo;
}

function upsertVideoById(items, nextVideo) {
  if (!nextVideo?.id) return items;
  let replaced = false;
  const nextItems = items.map((video) => {
    if (video.id !== nextVideo.id) return video;
    replaced = true;
    return { ...video, ...nextVideo };
  });
  return replaced ? nextItems : [nextVideo, ...nextItems];
}

function findDetailVideo(videoId) {
  if (!videoId) return videos[0] || progressVideos[0] || null;
  return videos.find((item) => item.id === videoId) || progressVideos.find((item) => item.id === videoId) || videos[0] || progressVideos[0] || null;
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
    if (extracted.status !== "completed") {
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
  if (shouldExtract && result.extraction?.status !== "completed") {
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

function confirmVideoDeletion(video) {
  const dialog = document.querySelector("#video-delete-dialog");
  if (dialog.open) return Promise.resolve(null);
  document.querySelector("#video-delete-name").textContent = video.title || video.id;
  const deleteClaims = document.querySelector("#video-delete-claims");
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
  const video = videos.find((item) => item.id === videoId) || progressVideos.find((item) => item.id === videoId);
  if (!video) return;
  deletingVideoIds.add(videoId);
  try {
    const confirmation = await confirmVideoDeletion(video);
    if (!confirmation) return;
    const scrollPosition = { left: window.scrollX, top: window.scrollY };
    const deletionView = activeView;
    await deleteJson(`${API_BASE}/videos/${videoId}?delete_claims=${confirmation.deleteClaims}`);
    removeVideoFromState(videoId, confirmation.deleteClaims);
    await Promise.allSettled([loadProgressSummary(), loadKnowledgePage(), loadVideoPage({ preserveLoaded: true }), refreshLibraryMetadata()]);
    renderAll();
    if (activeView === deletionView) {
      window.scrollTo({ ...scrollPosition, behavior: "instant" });
    }
  } finally {
    deletingVideoIds.delete(videoId);
  }
}

async function deleteClaim(claimId, videoId) {
  if (!adminSession.authenticated) {
    await loginAdmin();
    if (!adminSession.authenticated) return;
  }
  if (!confirm("确定删除这条观点吗？")) return;
  const result = await deleteJson(`${API_BASE}/claims/${claimId}`);
  removeClaimFromState(claimId, result.video_id || videoId);
  await Promise.allSettled([loadProgressSummary(), loadKnowledgePage()]);
  if (selectedVideoId) {
    await loadVideoDetail(selectedVideoId).catch(() => {});
  }
  renderAll();
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
  if (result.status !== "completed") {
    throw new Error(result.status || "extract_failed");
  }
  await loadApiData();
  selectedVideoId = result.video.id;
  renderAll();
  renderDetail();
  setView("detail");
  setQueueMessage(`已提取：${result.video.title}，新增 ${result.claims.length} 条观点。`, "ok");
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
  const isFailed = video.status === "transcript_failed" || Boolean(video.lastError) || live.stage === "failed";
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
  return tags
    .map((tag) => {
      const canOpenClaims = tag.key === "claims" && tag.state === "done" && (video.claimCount || video.claims.length) > 0;
      const tagName = canOpenClaims ? "button" : "span";
      const actionAttrs = canOpenClaims
        ? ` type="button" data-video-id="${escapeAttr(video.id)}" aria-label="查看 ${escapeAttr(video.title)} 的观点"`
        : "";
      return `
        <${tagName} class="progress-stage-tag" data-stage="${escapeAttr(tag.key)}" data-state="${escapeAttr(tag.state)}"${actionAttrs}>
          <strong>${escapeHtml(tag.title)}</strong>
          <em>${escapeHtml(tag.label)}</em>
        </${tagName}>
      `;
    })
    .join("");
}

function renderProgressTimeTags(video) {
  return getVideoProgressTimeItems(video)
    .map(
      (item) => `
        <span class="progress-time-tag">
          <strong>${escapeHtml(item.label)}</strong>
          <em>${escapeHtml(item.value)}</em>
        </span>
      `,
    )
    .join("");
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

function setView(view, options = {}) {
  if (!viewNames.has(view)) {
    view = "overview";
  }
  if (["deleted", "settings"].includes(view) && !adminSession.authenticated) {
    // Preserve a bookmarked admin view only while the initial session check is pending.
    if (adminSessionLoaded) history.replaceState({ view: "overview" }, "", "#overview");
    view = "overview";
    options = { ...options, updateHash: false };
  }
  activeView = view;
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
  if (options.updateHash !== false && window.location.hash !== `#${view}`) {
    history.pushState({ view }, "", `#${view}`);
  }
  if (options.render !== false) {
    renderCurrentView();
  }
  if (view === "settings" && options.load !== false) loadTranscriptSettings();
  if (view === "sources" && options.load !== false && adminSession.authenticated) {
    refreshDouyinLoginStatus().catch((error) => console.info("Douyin login check failed:", error.message));
  }
  if (view === "deleted" && options.load !== false) {
    loadDeletedItems();
  }
}

function syncViewFromHash() {
  const view = window.location.hash.replace(/^#/, "") || "overview";
  setView(viewNames.has(view) ? view : "overview", { updateHash: false });
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

function renderSources() {
  const sourceSummary = document.querySelector("#source-summary");
  if (sourceSummary) {
    const total = sources.reduce((sum, source) => sum + (normalizeCount(source.video_count) ?? 0), 0);
    sourceSummary.textContent = `${sources.length} 个来源，${total} 条入库视频。${window.DECOR_PUBLIC_LIBRARY ? "公开快照，仅供浏览与检索。" : "每位博主默认更新最新 5 条，自动跳过置顶。"}`;
  }
  const loginChecking = douyinLoginChecking || douyinLoginStatus.running;
  const loginUnknown = ["idle", "unknown"].includes(douyinLoginStatus.status) || douyinLoginStatus.logged_in == null;
  const loginType = loginChecking || loginUnknown ? "warn" : douyinLoginStatus.logged_in ? "done" : "";
  const loginLabel = loginChecking ? "登录检测中" : loginUnknown ? "登录态待确认"
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
      : `<article class="result-card"><h3>暂无来源</h3><p>先从“批量导入账号作品”保存一个博主来源。</p></article>`;
  document.querySelector("#source-grid").innerHTML = sourceGroups;
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
  let emptyState = `<article class="result-card"><h3>暂无视频</h3><p>这个来源还没有入库视频。</p></article>`;
  if (!visibleVideos.length && apiLoadState.status === "loading") {
    emptyState = `<article class="result-card"><h3>正在加载视频...</h3><p>正在连接本地接口，第 ${apiLoadState.attempts || 1} 次尝试。</p></article>`;
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
          const statusIcon = (complete) => `<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${complete ? '<path d="m3 8 3 3 7-7"/>' : '<path d="m4 4 8 8M12 4l-8 8"/>'}</svg>`;
          return `
        <article class="video-card">
          <div>
            <div class="video-content-status" aria-label="文案与观点状态">
              <span class="status ${hasTranscript ? "done" : "missing"}" title="${transcriptLabel}" aria-label="${transcriptLabel}">文案 ${statusIcon(hasTranscript)}</span>
              <span class="status ${hasClaims ? "done" : "missing"}" title="${claimsLabel}" aria-label="${claimsLabel}">观点 ${statusIcon(hasClaims)}</span>
            </div>
            ${renderAdBadge(video)}
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
  if (video.status === "claims_filtered") {
    return { key: "已完成", label: "已过滤", step: 3, retry: "完成" };
  }
  if (video.status === "transcript_failed" || video.lastError) {
    return { key: "失败", label: "失败", step: 1, retry: "重试" };
  }
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
  document.querySelector("#progress-tabs").innerHTML = tabs
    .map(
      (tab) => `
        <button class="filter-button ${activeProgressFilter === tab ? "active" : ""}" type="button" data-progress-filter="${escapeAttr(tab)}">
          ${escapeHtml(progressTabLabels[tab] || tab)} ${counts[tab] || 0}
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
          const reasonLabel = getVideoReasonLabel(video);
          const isDone = state.key === "已完成";
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
            <article class="progress-card">
              <span class="status ${isDone ? "done" : state.key === "失败" || state.key === "缺链接" ? "failed" : ""}">${escapeHtml(state.label)}</span>
              <div class="progress-card-main">
                <h3>${escapeHtml(video.title)}</h3>
                <p class="progress-creator-line">博主：${escapeHtml(video.creator || "未记录")}</p>
                <div class="progress-time-list" aria-label="视频时间">
                  ${timeTags}
                </div>
                <p>${video.retryCount ? `重试 ${video.retryCount} 次${video.retryCount >= 3 ? "，需确认" : ""}` : "未重试"}</p>
                ${reasonLabel ? `<p class="progress-reason-line">${escapeHtml(reasonLabel)}</p>` : ""}
                ${live.line ? `<p class="progress-live-line">${escapeHtml(live.line)}</p>` : ""}
              </div>
              <div class="progress-steps" aria-label="处理阶段">
                ${stageTags}
              </div>
              <footer>
                ${adminSession.authenticated ? `<button class="primary-button small red" type="button" data-progress-retry-video-id="${escapeAttr(video.id)}" data-progress-retry-state="${escapeAttr(state.key)}" ${adminActionAttributes()}>重试</button>` : ""}
                <button class="primary-button small" type="button" data-video-id="${escapeAttr(video.id)}">详情</button>
                ${
                  adminSession.authenticated
                    ? `<button class="primary-button small red" type="button" data-delete-video-id="${escapeAttr(video.id)}">删除视频</button>`
                    : ""
                }
              </footer>
            </article>
            ${rowLog}
          `;
        })
        .join("")}${paginationCard}`
    : `<article class="result-card"><h3>暂无视频</h3><p>当前筛选下没有需要处理的视频。</p></article>`;
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

async function openVideoClaims(videoId) {
  const dialog = document.querySelector("#video-claims-dialog");
  const content = document.querySelector("#video-claims-dialog-content");
  const title = document.querySelector("#video-claims-dialog-name");
  const video = videos.find((item) => item.id === videoId);
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
      ? claims.map((claim) => renderClaimCard(claim, { allowDelete: false })).join("")
      : '<p class="video-claims-notice" role="status">暂无观点，该视频尚未提取出可用观点。</p>';
  } catch (error) {
    if (!dialog.open || requestId !== videoClaimsRequestId) return;
    content.innerHTML = `<div class="video-claims-notice" role="alert"><p>观点加载失败：${escapeHtml(error.message)}</p><button class="primary-button small" type="button" data-video-claims-id="${escapeAttr(videoId)}">重试</button></div>`;
  } finally {
    if (requestId === videoClaimsRequestId) content.setAttribute("aria-busy", "false");
  }
}

function renderClaimCard(claim, { allowDelete = true } = {}) {
  const reasonItems = (Array.isArray(claim.reasons) ? claim.reasons : [claim.reasons]).filter(Boolean);
  const supplementary = [
    ["适用条件", claim.conditions],
    ["替代做法", claim.alternatives],
    ["价格信息", claim.priceInfo],
  ].filter(([, value]) => value && String(value).trim() !== "未提及");
  const tags = [...new Set([claim.stage, ...(claim.tags || [])].filter((tag) => tag && tag !== "未提及"))];
  const deleteButton =
    allowDelete && adminSession.authenticated && claim.id
      ? `<button class="primary-button small claim-delete-action" type="button" data-delete-claim-id="${escapeAttr(claim.id)}" data-delete-claim-video-id="${escapeAttr(claim.videoId || "")}" aria-label="删除观点：${escapeAttr(claim.object)}">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 6h18M9 6V4h6v2M5 6l1 14h12l1-14M10 10v6M14 10v6"/></svg>
          <span>删除观点</span>
        </button>`
      : "";
  return `
    <article class="result-card claim-card">
      <header class="claim-card-heading">
        <h3>${escapeHtml(claim.object)}</h3>
        <span class="status ${claim.stance.includes("不推荐") ? "failed" : claim.stance.includes("推荐") ? "done" : ""}">${escapeHtml(claim.stance)}</span>
      </header>
      ${claim.sourceVideoIsPromotional ? '<p class="promotion-source-notice">来源视频标记为推广</p>' : ""}
      <section class="claim-conclusion" aria-label="原文结论">
        <span class="claim-field-label">原文结论</span>
        <p>${escapeHtml(claim.conclusion || "未提及")}</p>
      </section>
      <section class="claim-reasons" aria-label="原文理由">
        <span class="claim-field-label">原文理由</span>
        ${reasonItems.length ? `<ul>${reasonItems.map((reason) => `<li>${escapeHtml(reason)}</li>`).join("")}</ul>` : '<p class="claim-muted">文案未提供理由</p>'}
      </section>
      ${supplementary.length ? `<dl class="claim-supplementary">${supplementary.map(([label, value]) => `<div><dt>${label}</dt><dd>${escapeHtml(value)}</dd></div>`).join("")}</dl>` : '<p class="claim-muted claim-supplementary-empty">文案未提供条件、替代做法或价格信息</p>'}
      <footer class="claim-card-footer">
        ${tags.length ? `<div class="claim-card-tags" aria-label="观点分类">${tags.map((tag) => `<span class="chip">${escapeHtml(tag)}</span>`).join("")}</div>` : ""}
        <div class="claim-card-actions">
          <a class="primary-button small claim-source-action" href="${safeUrl(claim.sourceUrl)}" target="_blank" rel="noreferrer">
            <span>查看来源</span>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M14 3h7v7M21 3 10 14M10 3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-5"/></svg>
          </a>
          ${deleteButton}
        </div>
      </footer>
    </article>
  `;
}

function getTranscriptEdit(videoId) {
  if (!transcriptEdits.has(videoId)) {
    transcriptEdits.set(videoId, { draft: null, editing: false, saving: false, message: "", type: "" });
  }
  return transcriptEdits.get(videoId);
}

function renderTranscriptEditor(video) {
  if (window.DECOR_PUBLIC_LIBRARY) return;
  const state = video ? getTranscriptEdit(video.id) : null;
  const editing = Boolean(state?.editing);
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
  if (!video?.detailLoaded) return;
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
  if (!video?.detailLoaded) return;
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
    state.message = `已保存 ${updated.transcriptLength} 字文案。现有知识卡已保留，需要更新时可点击“提取观点”。`;
    state.type = "ok";
    await Promise.allSettled([
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
  if (window.DECOR_PUBLIC_LIBRARY) return;
  const state = promotionEdits.get(video?.id);
  const review = video?.adReview;
  const manual = review?.source === "manual";
  const labels = { not_ad: "普通内容", uncertain: "疑似推广", error: "疑似推广", advertising: "推广" };
  document.querySelector("#promotion-current").textContent = `${labels[review?.decision] || "未识别"}${review?.decision ? manual ? "（手动设置）" : "（自动识别）" : ""}`;
  const select = document.querySelector("#promotion-decision");
  select.value = state?.draft ?? (manual ? review.decision : "auto");
  select.disabled = !adminSession.authenticated || !video?.detailLoaded || Boolean(state?.saving);
  const button = document.querySelector("#save-promotion");
  button.dataset.adminBlocked = String(!video?.detailLoaded);
  button.dataset.adminBusy = String(Boolean(state?.saving));
  button.textContent = state?.saving ? "保存中…" : "保存状态";
  document.querySelector("#promotion-message").textContent = state?.message || (manual ? "手动设置优先，后续自动识别不会覆盖。" : "管理员可手动修改；恢复自动识别不会立即发起模型调用。");
}

async function savePromotionEdit(event) {
  event.preventDefault();
  requireAdminAction();
  const video = findDetailVideo(selectedVideoId);
  if (!video?.detailLoaded || promotionEdits.get(video.id)?.saving) return;
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
    state.message = decision === "auto" ? "已恢复自动识别；无有效缓存时将在下次获取或保存文案时识别。" : "已保存，知识卡片来源提示已同步。手动设置不会被自动识别覆盖。";
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

function renderDetail() {
  const video = findDetailVideo(selectedVideoId);
  renderPromotionEditor(video);
  renderTranscriptEditor(video);
  const detailActions = document.querySelector(".detail-actions");
  if (!video) {
    document.querySelector("#detail-platform").textContent = "暂无视频";
    document.querySelector("#detail-heading").textContent = "暂无视频详情";
    document.querySelector("#detail-creator").textContent = "-";
    document.querySelector("#detail-claim-count").textContent = "0";
    document.querySelector("#detail-status").textContent = getVideoStatusLabel("empty");
    document.querySelector("#detail-link").href = "#";
    document.querySelector("#transcript-text").textContent = "暂无原始文案。";
    document.querySelector("#video-claims").innerHTML = `<article class="result-card"><h3>暂无观点</h3><p>当前还没有可展示的视频数据。</p></article>`;
    detailActions?.querySelector("[data-detail-delete-video]")?.remove();
    return;
  }
  detailActions?.querySelector("[data-detail-delete-video]")?.remove();
  if (adminSession.authenticated) {
    detailActions?.insertAdjacentHTML(
      "beforeend",
      `<button class="primary-button small red" type="button" data-detail-delete-video data-delete-video-id="${escapeAttr(video.id)}">删除视频</button>`,
    );
  }
  const reasonLabel = getVideoReasonLabel(video);
  document.querySelector("#detail-platform").textContent = `${video.platform} Source`;
  document.querySelector("#detail-heading").textContent = video.title;
  document.querySelector("#detail-creator").textContent = video.creator;
  document.querySelector("#detail-claim-count").textContent = video.claims.length;
  document.querySelector("#detail-status").textContent = reasonLabel ? `${getVideoStatusLabel(video.status)}｜${reasonLabel}` : getVideoStatusLabel(video.status);
  document.querySelector("#detail-link").href = video.sourceUrl;
  const hasFullTranscript = video.detailLoaded && Boolean(video.transcript?.trim());
  const transcriptFallback = "该视频尚未保存原始文案。";
  document.querySelector("#transcript-text").textContent = [
    `分享链接：${video.shareUrl || "未保存"}`,
    `分享文本：${video.shareText || "未保存"}`,
    ...(video.adReview?.reason ? ["", `推广识别：${getVideoReasonLabel(video) || "未发现明显推广结构"}`, ...(video.adReview.evidence || []).map((quote) => `依据：${quote}`)] : []),
    "",
    "原始文案：",
    hasFullTranscript ? video.transcript : transcriptFallback,
  ].join("\n");
  document.querySelector("#video-claims").innerHTML = video.claims.length
    ? video.claims
        .map((claim) =>
          renderClaimCard({
            ...claim,
            sourceUrl: video.sourceUrl,
          }),
        )
        .join("")
    : renderEmptyClaimsState(video, reasonLabel);
}

function renderEmptyClaimsState(video, reasonLabel = "") {
  if (video.status === "claims_filtered") {
    return `<article class="result-card claim-empty-card"><h3>无可用观点</h3><p>${escapeHtml(reasonLabel || "该视频没有可沉淀为知识库观点的内容。")}</p></article>`;
  }
  if (video.status === "transcript_failed") {
    return `<article class="result-card claim-empty-card"><h3>文案处理失败</h3><p>${escapeHtml(reasonLabel || "该视频尚未提取到可用文案。")}</p></article>`;
  }
  if (video.lastError) {
    return `<article class="result-card claim-empty-card"><h3>观点提取未完成</h3><p>${escapeHtml(reasonLabel)}</p></article>`;
  }
  return `<article class="result-card claim-empty-card"><h3>暂无观点</h3><p>当前视频尚未提取观点，或正在等待处理。</p></article>`;
}

function claimMatchesKnowledgeCategory(claim, category) {
  if (!category || category.type === "all") return true;
  if (category.type === "stage") return claim.stage === category.value;
  if (category.type === "stageGroup") return category.stages.includes(claim.stage);
  if (category.type === "tag") return claim.tags.includes(category.value) || claim.stage.includes(category.value);
  if (category.type === "stance") return claim.stance === category.value;
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
  const counts = category.type === "stage" ? knowledgeFacets.stages : category.type === "stance" ? knowledgeFacets.stances : knowledgeFacets.tags;
  return normalizeCount(counts[category.value]) ?? 0;
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
      : `<article class="result-card"><h3>${knowledgePageState.loading ? "正在加载观点..." : "暂无匹配观点"}</h3><p>${
          knowledgePageState.error ? escapeHtml(knowledgePageState.error) : "换一个流程阶段、标签或关键词试试。"
        }</p></article>`;
  renderKnowledgeCategories();
  setupAutoLoadMore();
}

function renderDeleted() {
  const container = document.querySelector("#deleted-list");
  if (!container) return;
  if (!adminSession.authenticated) {
    container.innerHTML = `
      <article class="result-card">
        <h3>需要管理员登录</h3>
        <p>登录后可以查看和恢复已删除的视频与观点。</p>
        <footer><button class="primary-button small red" type="button" id="admin-login-button-inline">管理员登录</button></footer>
      </article>
    `;
    return;
  }
  if (deletedItems.loading) {
    container.innerHTML = `<article class="result-card"><h3>正在加载...</h3><p>正在读取已删除数据。</p></article>`;
    return;
  }
  if (deletedItems.error) {
    container.innerHTML = `<article class="result-card"><h3>加载失败</h3><p>${escapeHtml(deletedItems.error)}</p></article>`;
    return;
  }
  const videoCards = deletedItems.videos
    .map(
      (video) => `
        <article class="video-card">
          <span class="status failed">已删除视频</span>
          <h3>${escapeHtml(video.title || video.id)}</h3>
          <p>${escapeHtml(video.creator || "未记录")} / ${escapeHtml(video.platform || "未记录")}</p>
          <div class="timeline-meta">
            <span class="chip">删除时间：${escapeHtml(formatEpochDateTime(video.deleted_at))}</span>
            <span class="chip">${escapeHtml(video.delete_reason || "未记录原因")}</span>
          </div>
          <footer>
            <button class="primary-button small red" type="button" data-restore-video-id="${escapeAttr(video.id)}">恢复视频</button>
            <a class="source-link compact-link" href="${safeUrl(video.source_url)}" target="_blank" rel="noreferrer">来源链接</a>
          </footer>
        </article>
      `,
    )
    .join("");
  const claimCards = deletedItems.claims
    .map(
      (claim) => `
        <article class="result-card claim-card">
          <span class="status failed">已删除观点</span>
          <h3>${escapeHtml(claim.object_name || claim.id)}</h3>
          <p><strong>来源视频：</strong>${escapeHtml(claim.video_title || claim.video_id || "未记录")}</p>
          <p><strong>原文结论：</strong>${escapeHtml(claim.original_conclusion || "未提及")}</p>
          <footer class="timeline-meta">
            <span class="chip">删除时间：${escapeHtml(formatEpochDateTime(claim.deleted_at))}</span>
            <span class="chip">${claim.video_deleted_at ? "需先恢复视频" : "可恢复"}</span>
            <button class="primary-button small red" type="button" data-restore-claim-id="${escapeAttr(claim.id)}" ${claim.video_deleted_at ? "disabled" : ""}>恢复观点</button>
          </footer>
        </article>
      `,
    )
    .join("");
  const hasDeletedItems = Boolean(videoCards || claimCards);
  container.innerHTML = hasDeletedItems
    ? `
        <article class="video-filter-notice">
          <span>已删除视频 ${deletedItems.videoTotal} 条 / 已删除观点 ${deletedItems.claimTotal} 条</span>
        </article>
        ${videoCards}
        ${claimCards}
      `
    : `<article class="result-card"><h3>暂无已删除数据</h3><p>当前没有软删除的视频或观点。</p></article>`;
}

function renderSettings() {
  const root = document.querySelector("#transcript-settings");
  if (!root) return;
  const state = transcriptSettings;
  const blocked = state.busy || state.loading || !state.provider;
  const label = state.provider === "local_asr" ? "本地 ASR" : state.provider === "transcriptgenerate" ? "API 转写" : "读取中…";
  root.setAttribute("aria-busy", String(state.busy || state.loading));
  root.innerHTML = `
    <div class="settings-current"><span>当前方式</span><strong>${label}</strong><small>保存后立即生效，并在重启后保留。</small></div>
    <div class="transcript-provider-grid">
      <article class="transcript-provider-card ${state.provider === "transcriptgenerate" ? "selected" : ""}">
        <p class="eyebrow">REMOTE / API</p><h3>API 转写</h3>
        <p>使用已有配置的 TranscriptGenerate 转写接口与账号额度。无需本机运行识别模型。</p>
        <button class="primary-button" data-select-transcript-provider="transcriptgenerate" ${adminActionAttributes(blocked || state.provider === "transcriptgenerate")}>${state.provider === "transcriptgenerate" ? "当前已启用" : "切换为 API"}</button>
      </article>
      <article class="transcript-provider-card ${state.provider === "local_asr" ? "selected" : ""}">
        <p class="eyebrow">LOCAL / CPU</p><h3>本地 ASR</h3>
        <p>使用 SenseVoiceSmall INT8，在本机 CPU 上识别。切换前自动检测依赖、模型加载及实际推理，检测失败不切换。</p>
        <button class="primary-button" data-select-transcript-provider="local_asr" ${adminActionAttributes(blocked || state.provider === "local_asr")}>${state.provider === "local_asr" ? "当前已启用" : "检测并切换为本地"}</button>
      </article>
    </div>
    <div class="local-asr-health" data-status="${escapeAttr(state.health?.status || "unknown")}">
      <div><strong>本地服务状态</strong><p>${escapeHtml(state.health?.message || "尚未检测。本地 worker 按需启动，无需单独保持常驻进程。")}</p></div>
      <button class="primary-button small" id="check-local-asr" ${adminActionAttributes(state.busy || state.loading)}>${state.busy ? "处理中…" : "检测本地服务"}</button>
    </div>
    <p class="settings-feedback" id="transcript-settings-message" role="status" data-error="${Boolean(state.error)}">${escapeHtml(state.error || state.message)}</p>
    <p class="settings-note">${adminSession.authenticated ? "仅影响后续转写；已保存文案不会重录，进行中的任务保持原方式。" : "请先登录管理员，再检测或修改转写方式。"} 本地检测不验证抖音登录与下载权限，也不会调用外部转写服务。未完成的旧 API 任务需先核对，避免重复提交。</p>
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

  const videoButton = event.target.closest("[data-video-id]");
  if (videoButton) {
    selectedVideoId = videoButton.dataset.videoId;
    renderDetail();
    setView("detail");
    loadVideoDetail(selectedVideoId)
      .then(() => {
        renderDetail();
        renderVideos();
        renderProgress();
      })
      .catch((error) => {
        document.querySelector("#video-claims").innerHTML = `<article class="result-card"><h3>详情加载失败</h3><p>${escapeHtml(error.message)}</p></article>`;
      });
    return;
  }

  const backToVideosButton = event.target.closest("#back-to-videos");
  if (backToVideosButton) {
    setView("videos");
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
    if (event.target.closest("button, a")) return;
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
    const video = videos.find((item) => item.id === videoId);
    let force = false;
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
        progressRetryButton.textContent = "重试";
      });
    return;
  }

  const transcriptButton = event.target.closest("#fetch-transcript");
  if (transcriptButton) {
    requireAdminAction();
    const videoId = selectedVideoId;
    const video = findDetailVideo(videoId);
    if (!video?.detailLoaded || hasVideoTranscript(video) || videoTranscriptions.get(videoId)?.running) return;
    const state = { running: true, message: "正在获取文案，请稍候…", type: "" };
    videoTranscriptions.set(videoId, state);
    getTranscriptEdit(videoId).message = "";
    renderDetail();
    postJson(`${API_BASE}/videos/${videoId}/transcript/retry`, {})
      .then(async () => {
        state.message = "文案已保存。可点击“提取观点”生成知识卡。";
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
    const state = { running: true, message: "正在提取观点，请稍候…", type: "" };
    videoExtractions.set(videoId, state);
    renderIfActive("detail", "videos");
    setAdminActionBusy(extractButton, true);
    extractButton.textContent = "提取中";
    postJson(`${API_BASE}/videos/${videoId}/extract`, {})
      .then(async (result) => {
        if (!["completed", "filtered"].includes(result.status)) throw new Error(result.status || "extract_failed");
        state.message = result.status === "filtered" ? "本次未提取到可靠知识，已保留原文案。" : `提取完成，保存 ${(result.claims || []).length} 条观点。`;
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
          ? "模型响应超时，文案和已有知识卡已保留。请稍后重试提取观点。"
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

document.addEventListener("click", (event) => {
  const submitButton = event.target.closest("#ingest-form button[type='submit']");
  if (submitButton) {
    ingestSubmitMode = submitButton.dataset.mode || "save";
  }
});

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && adminLoginModal && !adminLoginModal.hidden) {
    event.preventDefault();
    closeAdminLoginModal();
    return;
  }
  if (event.key !== "Enter" && event.key !== " ") return;
  const sourceFilterCard = event.target.closest("[data-source-filter-id]");
  if (!sourceFilterCard || event.target.closest("button, a")) return;
  event.preventDefault();
  applySourceFilter(sourceFilterCard.dataset.sourceFilterId, sourceFilterCard.dataset.sourceFilterName);
});

function renderAll() {
  renderCurrentView();
}

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
