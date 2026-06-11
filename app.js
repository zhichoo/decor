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
  const params = new URLSearchParams(window.location.search);
  const explicitApiOrigin = normalizeApiOrigin(params.get("api") || window.ZHUANGXIU_API_ORIGIN);
  if (explicitApiOrigin) {
    localStorage.setItem("zhuangxiuApiOrigin", explicitApiOrigin);
    return `${explicitApiOrigin}/api`;
  }
  const storedApiOrigin = normalizeApiOrigin(localStorage.getItem("zhuangxiuApiOrigin"));
  if (window.location.protocol === "http:" || window.location.protocol === "https:") {
    const currentOrigin = normalizeApiOrigin(window.location.origin);
    if (storedApiOrigin) return `${storedApiOrigin}/api`;
    if (currentOrigin === DEFAULT_LOCAL_API_ORIGIN) return `${currentOrigin}/api`;
    return `${DEFAULT_LOCAL_API_ORIGIN}/api`;
  }
  if (storedApiOrigin) return `${storedApiOrigin}/api`;
  return `${DEFAULT_LOCAL_API_ORIGIN}/api`;
}

const API_BASE = resolveApiBase();
const API_CACHE_KEY = "zhuangxiuApiSnapshot:v1";
const API_CACHE_MAX_AGE = 10 * 60 * 1000;

const fallbackVideos = [];


const knowledgeCategoryGroups = [
  {
    title: "范围",
    items: [{ type: "all", value: "全部", label: "全部观点", meta: "所有知识卡" }],
  },
  {
    title: "按流程大类",
    items: [
      { type: "stageGroup", value: "前期规划", label: "前期规划", meta: "准备 / 验房 / 设计", stages: ["准备阶段", "收房验房", "设计规划"] },
      { type: "stageGroup", value: "基础施工", label: "基础施工", meta: "拆改 / 水电 / 防水", stages: ["拆改阶段", "水电阶段", "防水阶段"] },
      { type: "stageGroup", value: "泥木油工", label: "泥木油工", meta: "瓦工 / 木工 / 墙面", stages: ["瓦工阶段", "木工阶段", "油工阶段"] },
      {
        type: "stageGroup",
        value: "安装收口",
        label: "安装收口",
        meta: "主材 / 定制 / 厨卫 / 五金",
        stages: ["主材安装", "定制柜安装", "厨卫安装", "灯具开关五金"],
      },
      { type: "stageGroup", value: "软装入住", label: "软装入住", meta: "家具 / 家电 / 验收", stages: ["家电家具软装", "开荒保洁", "通风除醛", "入住验收"] },
    ],
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
};
const viewNames = new Set(Object.keys(viewTitles));

function getInitialView() {
  const hashView = window.location.hash.replace(/^#/, "");
  return viewNames.has(hashView) ? hashView : "overview";
}

let videos = fallbackVideos;
let sources = [];
let knowledgeClaims = [];
let activeView = getInitialView();
let selectedVideoId = videos[0]?.id || null;
let activeSourceFilter = null;
let activeVideoPlatform = "全部";
let activeVideoCreator = "全部";
let activeKnowledgeCategory = { type: "all", value: "全部" };
let activeKnowledgeGroupTitle = "范围";
let activeProgressFilter = "全部";
let ingestSubmitMode = "save";
let queueStatusTimer = null;
let activeProgressLogVideoId = null;
let lastQueueStatus = null;
let queueLogMode = "global";
let apiLoadState = { status: "loading", error: "", attempts: 0 };
let apiHealthState = { ok: true, dbAvailable: true, dbMessage: "" };
let apiStats = { sourceCount: null, videoCount: null, transcriptCount: null, claimCount: null };
let apiLoadRequestId = 0;
let douyinLoginStatus = { status: "idle", message: "未检查", running: false, logged_in: false };
let douyinLoginTimer = null;

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
const knowledgeLayout = document.querySelector("#knowledge-layout");
const knowledgeFilterToggle = document.querySelector("#knowledge-filter-toggle");
const knowledgeFilterCurrent = document.querySelector("#knowledge-filter-current");
const progressProcessPendingButton = document.querySelector("#progress-process-pending");
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
  const count = Number(value);
  return Number.isFinite(count) ? count : null;
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
  return firstKnownCount(apiStats.claimCount, claims.length || null, videos.reduce((sum, video) => sum + (video.claimCount || 0), 0));
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

function sortVideosByPublishTime(items) {
  return [...items].sort((a, b) => getVideoPublishTimestamp(b) - getVideoPublishTimestamp(a));
}

function normalizeApiClaim(claim) {
  const reasons = Array.isArray(claim.original_reasons) ? claim.original_reasons : claim.original_reasons ? [claim.original_reasons] : [];
  const alternatives = Array.isArray(claim.alternatives) ? claim.alternatives.join("；") : claim.alternatives || "";
  return {
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
    publishTime: video.published_at || "未提及",
    claimCount: video.claim_count || 0,
    retryCount: video.retry_count || 0,
    lastError: video.last_error || "",
    hasTranscript: Boolean(video.has_transcript || transcriptLength > 0),
    transcriptLength,
    transcript: transcriptText || "未保存原始文案",
    claims: Array.isArray(video.claims) ? video.claims.map(normalizeApiClaim) : [],
  };
}

function hasVideoTranscript(video) {
  return Boolean(video?.hasTranscript || (video?.transcript && !video.transcript.includes("未保存")));
}

function getVideoTranscriptLabel(video) {
  if (!hasVideoTranscript(video)) return "待提取";
  return video.transcriptLength > 0 ? `${video.transcriptLength} 字` : "已获取";
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
        videos,
        knowledgeClaims,
        apiStats,
      }),
    );
  } catch (error) {
    console.info("API cache write failed:", error.message);
  }
}

function applyApiSnapshot(snapshot) {
  sources = snapshot.sources;
  videos = sortVideosByPublishTime(snapshot.videos);
  knowledgeClaims = snapshot.knowledgeClaims;
  apiStats = snapshot.apiStats || apiStats;
  if (activeSourceFilter && !sources.some((source) => source.id === activeSourceFilter.id)) {
    activeSourceFilter = null;
  }
  if (!selectedVideoId || !videos.some((video) => video.id === selectedVideoId)) {
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
  if (!selectedVideoId || !videos.some((video) => video.id === selectedVideoId)) {
    selectedVideoId = videos[0]?.id || null;
  }
}

function applyBootstrapPayload(payload) {
  applyApiHealth(payload.health || {});
  const knowledgePayload = payload.knowledge || {};
  apiStats = normalizeApiStats(payload.stats || {});
  const collections = {
    nextSources: payload.sources || [],
    nextVideos: (payload.videos || []).map(normalizeApiVideo),
  };
  if (!knowledgePayload.deferred) {
    collections.nextKnowledgeClaims = (knowledgePayload.claims || []).map(normalizeKnowledgeClaim);
  }
  applyApiCollections(collections);
}

function loadKnowledgeClaimsInBackground(requestId) {
  fetchApiJson("/knowledge")
    .then((payload) => {
      if (requestId !== apiLoadRequestId) return;
      knowledgeClaims = (payload.claims || []).map(normalizeKnowledgeClaim);
      apiStats = {
        ...apiStats,
        claimCount: knowledgeClaims.length,
      };
      renderOverview();
      renderDetail();
      renderKnowledgeCategories();
      renderKnowledge();
      writeApiCache();
    })
    .catch((error) => {
      console.info("Knowledge data load failed:", error.message);
    });
}

async function fetchApiJson(path) {
  const response = await fetch(`${API_BASE}${path}`);
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
    applyBootstrapPayload(bootstrapPayload);
    apiLoadState = { status: "ready", error: "", attempts: attempt };
    renderAll();
    writeApiCache();
    if (bootstrapPayload.knowledge?.deferred) {
      loadKnowledgeClaimsInBackground(requestId);
    }
    return;
  } catch (error) {
    console.info("Bootstrap data load failed, falling back to split endpoints:", error.message);
  }

  const healthPromise = fetchApiJson("/health");
  const sourcesPromise = fetchApiJson("/sources").then((payload) => payload.sources || []);
  const videosPromise = fetchApiJson("/videos").then((payload) => sortVideosByPublishTime((payload.videos || []).map(normalizeApiVideo)));
  const knowledgePromise = fetchApiJson("/knowledge")
    .then((payload) => (payload.claims || []).map(normalizeKnowledgeClaim))
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
      videos = videosResult.value;
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
      videoCount: videos.length,
      transcriptCount: videos.filter(hasVideoTranscript).length,
    };
    renderAll();
    writeApiCache();

    knowledgePromise.then((claims) => {
      if (requestId !== apiLoadRequestId || !claims) return;
      knowledgeClaims = claims;
      apiStats = {
        ...apiStats,
        claimCount: knowledgeClaims.length,
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
  const detailResponse = await fetch(`${API_BASE}/videos/${videoId}`);
  if (!detailResponse.ok) throw new Error(`video ${videoId} ${detailResponse.status}`);
  const detail = await detailResponse.json();
  const detailedVideo = normalizeApiVideo({
    ...detail.video,
    claim_count: detail.claims.length,
    claims: detail.claims,
  });
  videos = videos.map((video) => (video.id === videoId ? detailedVideo : video));
  selectedVideoId = videoId;
  writeApiCache();
  return detailedVideo;
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
  ingestPanel.hidden = !isOpen;
  if (isOpen) {
    setView("sources");
    setIngestMessage("");
    ingestForm.querySelector("textarea[name='batch_profile_url']").focus();
  }
}

async function postJson(url, payload) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(data.error || data.message || `${response.status}`);
  }
  return data;
}

async function getJson(url) {
  const response = await fetch(url);
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

async function batchCollectVideos(payload) {
  if (!payload.batch_profile_url) {
    throw new Error("请填写主页链接");
  }
  const limit = Number(payload.batch_limit) || 5;
  const profileUrl = payload.batch_profile_url;
  const existingSource = sources.find((source) => source.profile_url === profileUrl || source.profile_url?.split("?")[0] === profileUrl.split("?")[0]);

  setIngestMessage("正在更新主页最新作品...");
  let sourceId = existingSource?.id;
  if (!sourceId) {
    const created = await postJson(`${API_BASE}/sources`, {
      platform: payload.batch_platform,
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
  setIngestOpen(false);
  ingestForm.reset();
  setIngestMessage(
    result.stats
      ? `更新完成：保存 ${result.stats.saved} 条，新增 ${result.stats.created} 条，重复 ${result.stats.duplicate} 条。`
      : "",
  );
}

async function updateSource(sourceId) {
  setSourceMessage("正在请求更新来源...");
  const result = await postJson(`${API_BASE}/sources/${sourceId}/update`, { limit: 5 });
  await loadApiData();
  renderAll();
  setView("sources");
  setSourceMessage(
    result.stats
      ? `更新完成：保存 ${result.stats.saved} 条，新增 ${result.stats.created} 条，重复 ${result.stats.duplicate} 条。`
      : result.message || result.status,
    "ok",
  );
}

async function updateAllSources() {
  setSourceMessage("正在请求更新所有来源...");
  const result = await postJson(`${API_BASE}/sources/update-all`, { limit: 5 });
  await loadApiData();
  renderAll();
  setView("sources");
  setSourceMessage(result.message || result.status, result.status === "collector_not_ready" ? "warn" : "ok");
}

async function refreshDouyinLoginStatus() {
  const status = await getJson(`${API_BASE}/douyin/login-status`);
  douyinLoginStatus = status;
  renderSources();
  if (!status.running && douyinLoginTimer) {
    clearInterval(douyinLoginTimer);
    douyinLoginTimer = null;
  }
  return status;
}

async function startDouyinLogin(profileUrl) {
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
  progressProcessPendingButton.disabled = state === "starting" || state === "running";
  if (labelEl) labelEl.textContent = label;
}

async function locateNextTranscriptVideo() {
  setQueueMessage("正在查找下一条待文案视频...");
  const result = await getJson(`${API_BASE}/queue/next`);
  if (!result.next_transcript) {
    setQueueMessage("没有待文案视频。", "ok");
    return;
  }
  selectedVideoId = result.next_transcript.id;
  await loadApiData();
  selectedVideoId = result.next_transcript.id;
  renderAll();
  renderDetail();
  setView("detail");
  setQueueMessage(`待文案：${result.next_transcript.title}`, "ok");
}

async function extractNextQueuedVideo() {
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
  setProgressMessage("正在重新提取视频文案...");
  const result = await postJson(`${API_BASE}/videos/${videoId}/transcript/retry`, {});
  await loadApiData();
  renderAll();
  setView("progress");
  setProgressMessage(`文案已保存：${result.video.title}`, "ok");
}

async function processPendingQueue(limit = 5) {
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
  const bodyText = (status.logs || []).join("\n") || "[--:--:--] 等待自动队列启动...";
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
    queueLogBody.textContent = bodyText;
    queueLogBody.scrollTop = queueLogBody.scrollHeight;
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
    rowBody.textContent = bodyText;
    rowBody.scrollTop = rowBody.scrollHeight;
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
  if (processed.length) return "处理完成，观点已入库";
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
      label: claimCount > 0 ? `${claimCount} 条` : isFiltered ? "已过滤" : "待提取",
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
    .map(
      (tag) => `
        <span class="progress-stage-tag" data-stage="${tag.key}" data-state="${tag.state}">
          <strong>${tag.title}</strong>
          <em>${tag.label}</em>
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

async function pollQueueStatus() {
  const status = await getJson(`${API_BASE}/queue/status`);
  renderQueueStatus(status);
  if (activeView === "progress") {
    renderProgress();
    renderQueueStatus(status);
  }
  if (queueLogMode === "global" && status.running) {
    setProgressRunButtonState("running", "处理中...");
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

async function startVideoRetryJob(videoId, force = false) {
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
  activeView = view;
  document.querySelectorAll(".view").forEach((el) => el.classList.remove("active"));
  document.querySelector(`#${view}-view`).classList.add("active");
  document.querySelectorAll(".nav-item").forEach((button) => {
    button.classList.toggle("active", button.dataset.view === view);
  });
  pageTitle.textContent = viewTitles[view];
  if (openIngestButton) {
    openIngestButton.hidden = view !== "sources";
  }
  if (view !== "sources" && ingestPanel) {
    ingestPanel.hidden = true;
  }
  if (options.updateHash !== false && window.location.hash !== `#${view}`) {
    history.pushState({ view }, "", `#${view}`);
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
  const claims = getAllClaims();
  document.querySelector("#metric-stages").textContent = stages.length;
  document.querySelector("#metric-notes").textContent = overviewProcessNodes.length;
  document.querySelector("#metric-dos").textContent = firstKnownCount(apiStats.videoCount, videos.length);
  document.querySelector("#metric-donts").textContent = getClaimTotal();

  const colors = ["#0f7a4d", "#e33b2f", "#1456a3", "#f2c230"];
  document.querySelector("#timeline").innerHTML = stages
    .map((stage, index) => {
      const count = claims.filter((claim) => claim.stage === stage.name).length;
      return `
        <article class="timeline-card" style="--accent: ${colors[index % colors.length]}">
          <button type="button" aria-label="查看${stage.name}" data-knowledge-stage="${stage.name}"></button>
          <span class="eyebrow">阶段 ${String(index + 1).padStart(2, "0")}</span>
          <h3>${stage.name}</h3>
          <p>${stage.desc}</p>
          <div class="timeline-meta">
            <span class="chip">${count} 条观点</span>
            <span class="chip">风险 ${stage.risk}</span>
          </div>
        </article>
      `;
    })
    .join("");
}

function renderSources() {
  const loginType = douyinLoginStatus.logged_in ? "done" : douyinLoginStatus.running ? "warn" : "";
  const loginLabel = douyinLoginStatus.logged_in ? "抖音已登录" : douyinLoginStatus.running ? "登录检测中" : "抖音未登录";
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
    <article class="source-card" role="button" tabindex="0" data-source-filter-id="${source.id}" data-source-filter-name="${source.name}">
      <div>
        <span class="status ${source.status === "active" ? "done" : ""}">${source.status}</span>
        <h3>${source.name}</h3>
        <p>${source.platform} / ${source.priority}</p>
      </div>
      <div class="timeline-meta">
        <span class="chip">${source.video_count || 0} 条视频</span>
        <span class="chip">${source.pending_count || 0} 条文案待提取</span>
        <span class="chip">${source.claim_count || 0} 条观点</span>
      </div>
      <footer>
        <button class="primary-button small red" type="button" data-update-source-id="${source.id}">更新 5 条</button>
        <a class="source-link compact-link" href="${source.profile_url || "#"}" target="_blank" rel="noreferrer">主页链接</a>
      </footer>
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
                  <div>
                    <span class="status ${isDouyin ? loginType : ""}">${isDouyin ? loginLabel : platform}</span>
                    <h3>${platform}</h3>
                    <p>${groupSources.length} 个博主 / ${groupVideoCount} 条视频 / ${groupPendingCount} 条文案待提取</p>
                  </div>
                  ${
                    isDouyin
                      ? `<div class="source-group-actions">
                          <button class="primary-button small" type="button" id="check-douyin-login">检查登录态</button>
                          <button class="primary-button small" type="button" data-douyin-login-url="${loginProfileUrl}">登录抖音</button>
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
          <span>${label}</span>
          <strong>${count}</strong>
        </article>
      `,
    )
    .join("");
}

function renderVideoFilters() {
  const panel = document.querySelector("#video-filter-panel");
  if (!panel) return;
  const platforms = ["全部", ...new Set(videos.map((video) => video.platform).filter(Boolean))];
  const platformScopedVideos = activeVideoPlatform === "全部" ? videos : videos.filter((video) => video.platform === activeVideoPlatform);
  const creators = ["全部", ...new Set(platformScopedVideos.map((video) => video.creator).filter(Boolean))];
  if (!creators.includes(activeVideoCreator)) {
    activeVideoCreator = "全部";
  }
  panel.innerHTML = `
    <section class="video-filter-group" aria-label="按平台筛选">
      <span>平台</span>
      <div>
        ${platforms
          .map(
            (platform) => `
              <button class="filter-button ${activeVideoPlatform === platform ? "active" : ""}" type="button" data-video-platform="${platform}">
                ${platform}
              </button>
            `,
          )
          .join("")}
      </div>
    </section>
    <section class="video-filter-group" aria-label="按博主筛选">
      <span>博主</span>
      <div>
        ${creators
          .map(
            (creator) => `
              <button class="filter-button ${activeVideoCreator === creator ? "active" : ""}" type="button" data-video-creator="${creator}">
                ${creator}
              </button>
            `,
          )
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
        <span>当前来源：${activeSourceFilter.name}</span>
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
        <p>${apiLoadState.error || "本地服务暂时不可用"}。</p>
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
          const extractLabel = hasClaims ? "已提取" : isFiltered ? "已过滤" : hasTranscript ? "提取观点" : "待文案";
          const extractDisabled = hasClaims || isFiltered || !hasTranscript ? "disabled" : "";
          return `
        <article class="video-card">
          <div>
            <span class="status ${video.status === "已入库" ? "done" : ""}">${video.status}</span>
            <h3>${video.title}</h3>
            <p>${video.creator} / ${video.platform}</p>
          </div>
          <div class="timeline-meta">
            <span class="chip">${video.publishTime}</span>
            <span class="chip">${video.shareUrl ? "有分享链" : "无分享链"}</span>
            <span class="chip">${video.claimCount} 条观点</span>
          </div>
          <footer>
            <button class="primary-button small" type="button" data-video-id="${video.id}">查看详情</button>
            <button class="primary-button small red" type="button" data-extract-video-id="${video.id}" ${extractDisabled}>${extractLabel}</button>
            <a class="source-link compact-link" href="${video.sourceUrl}" target="_blank" rel="noreferrer">来源链接</a>
          </footer>
        </article>
      `;
        })
        .join("")
    : emptyState;
  document.querySelector("#video-grid").innerHTML = filterNotice + videoCards;
}

function getVideoProgressState(video) {
  const hasTranscript = hasVideoTranscript(video);
  const claimCount = video.claimCount || video.claims.length;
  if (video.status === "transcript_failed" || video.lastError) {
    return { key: "失败", label: "失败", step: 1, retry: "重试" };
  }
  if (video.status === "claims_filtered") {
    return { key: "已完成", label: "已过滤", step: 3, retry: "完成" };
  }
  if (!video.sourceUrl && !video.shareUrl) {
    return { key: "缺链接", label: "缺链接", step: 0, retry: "获取链接" };
  }
  if (claimCount > 0) {
    return { key: "已完成", label: "已完成", step: 3, retry: "完成" };
  }
  if (hasTranscript) {
    return { key: "待观点", label: "待观点", step: 2, retry: "重试" };
  }
  return { key: "待文案", label: "待文案", step: 1, retry: "重试" };
}

function renderProgress() {
  const sortedVideos = sortVideosByPublishTime(videos);
  const counts = sortedVideos.reduce(
    (acc, video) => {
      const state = getVideoProgressState(video);
      acc[state.key] = (acc[state.key] || 0) + 1;
      acc["全部"] += 1;
      return acc;
    },
    { 全部: 0, 缺链接: 0, 待文案: 0, 待观点: 0, 已完成: 0, 失败: 0 },
  );
  const tabs = ["全部", "缺链接", "待文案", "待观点", "已完成", "失败"];
  document.querySelector("#progress-tabs").innerHTML = tabs
    .map(
      (tab) => `
        <button class="filter-button ${activeProgressFilter === tab ? "active" : ""}" type="button" data-progress-filter="${tab}">
          ${tab} ${counts[tab] || 0}
        </button>
      `,
    )
    .join("");

  const visibleVideos = sortedVideos.filter((video) => {
    const state = getVideoProgressState(video);
    return activeProgressFilter === "全部" || state.key === activeProgressFilter;
  });

  document.querySelector("#progress-list").innerHTML = visibleVideos.length
    ? visibleVideos
        .map((video) => {
          const state = getVideoProgressState(video);
          const stageTags = renderProgressStageTags(video);
          const live = getLiveProgressStage(video);
          const isDone = state.key === "已完成";
          const rowLog =
            activeProgressLogVideoId === video.id
              ? `
                <details class="queue-log-panel row-log-panel" data-row-log-video-id="${video.id}" open>
                  <summary>
                    <span data-row-log-title>${escapeHtml(lastQueueStatus && lastQueueStatus.job_id ? getQueueResultText(lastQueueStatus) || "本条重试日志" : "本条重试日志")}</span>
                    <small data-row-log-meta>${escapeHtml(lastQueueStatus?.job_id ? `${lastQueueStatus.job_id} / ${lastQueueStatus.running ? "运行中" : "已结束"}` : "准备启动...")}</small>
                    <button class="log-close-button" type="button" data-close-row-log aria-label="关闭重试日志">关闭</button>
                  </summary>
                  <pre data-row-log-body>${escapeHtml(lastQueueStatus?.logs?.length ? lastQueueStatus.logs.join("\n") : "[--:--:--] 等待重试启动...")}</pre>
                </details>
              `
              : "";
          return `
            <article class="progress-card">
              <span class="status ${isDone ? "done" : state.key === "失败" || state.key === "缺链接" ? "failed" : ""}">${state.label}</span>
              <div class="progress-card-main">
                <h3>${video.title}</h3>
                <p>${video.creator} / ${video.publishTime}</p>
                <p>${video.retryCount ? `重试 ${video.retryCount} 次${video.retryCount >= 3 ? "，需确认" : ""}` : "未重试"}${video.lastError ? ` / ${video.lastError}` : ""}</p>
                ${live.line ? `<p class="progress-live-line">${escapeHtml(live.line)}</p>` : ""}
              </div>
              <div class="progress-steps" aria-label="处理阶段">
                ${stageTags}
              </div>
              <footer>
                <button class="primary-button small red" type="button" data-progress-retry-video-id="${video.id}" data-progress-retry-state="${state.key}">重试</button>
                <button class="primary-button small" type="button" data-video-id="${video.id}">详情</button>
              </footer>
            </article>
            ${rowLog}
          `;
        })
        .join("")
    : `<article class="result-card"><h3>暂无视频</h3><p>当前筛选下没有需要处理的视频。</p></article>`;
}

function applySourceFilter(sourceId, sourceName) {
  activeSourceFilter = {
    id: sourceId,
    name: sourceName,
  };
  activeVideoPlatform = "全部";
  activeVideoCreator = "全部";
  renderVideos();
  setView("videos");
}

function renderClaimCard(claim) {
  const reasonItems = Array.isArray(claim.reasons) ? claim.reasons : [claim.reasons];
  return `
    <article class="result-card claim-card">
      <span class="status ${claim.stance.includes("不推荐") ? "failed" : claim.stance.includes("推荐") ? "done" : ""}">
        ${claim.stance}
      </span>
      <h3>${claim.object}</h3>
      <p><strong>原文结论：</strong>${claim.conclusion}</p>
      <p><strong>原文理由：</strong>${reasonItems.join("；") || "未提及"}</p>
      <p><strong>条件：</strong>${claim.conditions || "未提及"}</p>
      <p><strong>替代做法：</strong>${claim.alternatives || "未提及"}</p>
      <p><strong>价格信息：</strong>${claim.priceInfo || "未提及"}</p>
      <footer class="timeline-meta">
        <span class="chip">${claim.stage}</span>
        ${claim.tags.map((tag) => `<span class="chip">${tag}</span>`).join("")}
        <a class="chip link-chip" href="${claim.sourceUrl}" target="_blank" rel="noreferrer">来源视频</a>
      </footer>
    </article>
  `;
}

function renderDetail() {
  const video = videos.find((item) => item.id === selectedVideoId) || videos[0];
  if (!video) {
    document.querySelector("#detail-platform").textContent = "暂无视频";
    document.querySelector("#detail-heading").textContent = "暂无视频详情";
    document.querySelector("#detail-creator").textContent = "-";
    document.querySelector("#detail-claim-count").textContent = "0";
    document.querySelector("#detail-status").textContent = "empty";
    document.querySelector("#detail-link").href = "#";
    document.querySelector("#transcript-text").textContent = "暂无原始文案。";
    document.querySelector("#video-claims").innerHTML = `<article class="result-card"><h3>暂无观点</h3><p>当前还没有可展示的视频数据。</p></article>`;
    return;
  }
  document.querySelector("#detail-platform").textContent = `${video.platform} Source`;
  document.querySelector("#detail-heading").textContent = video.title;
  document.querySelector("#detail-creator").textContent = video.creator;
  document.querySelector("#detail-claim-count").textContent = video.claims.length;
  document.querySelector("#detail-status").textContent = video.status;
  document.querySelector("#detail-link").href = video.sourceUrl;
  document.querySelector("#transcript-text").textContent = [
    `分享链接：${video.shareUrl || "未保存"}`,
    `分享文本：${video.shareText || "未保存"}`,
    "",
    "原始文案：",
    video.transcript && !video.transcript.includes("未保存") ? video.transcript : "正在加载详情，或该视频尚未提取原始文案。",
  ].join("\n");
  document.querySelector("#video-claims").innerHTML = video.claims
    .map((claim) =>
      renderClaimCard({
        ...claim,
        sourceUrl: video.sourceUrl,
      }),
    )
    .join("");
}

function claimMatchesKnowledgeCategory(claim, category) {
  if (!category || category.type === "all") return true;
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

function getKnowledgeCategoryLabel(category = activeKnowledgeCategory) {
  return category?.label || category?.value || "全部观点";
}

function setKnowledgeFilterExpanded(expanded) {
  if (!knowledgeLayout || !knowledgeFilterToggle) return;
  knowledgeLayout.classList.toggle("is-filter-collapsed", !expanded);
  knowledgeFilterToggle.setAttribute("aria-expanded", String(expanded));
}

function syncKnowledgeFilterSummary() {
  if (!knowledgeFilterCurrent) return;
  knowledgeFilterCurrent.textContent = getKnowledgeCategoryLabel();
}

function findKnowledgeCategory(type, value) {
  return knowledgeCategoryGroups.flatMap((group) => group.items).find((item) => item.type === type && item.value === value);
}

function renderKnowledgeCategories() {
  const claims = getAllClaims();
  const activeKey = getActiveKnowledgeCategoryKey();
  const activeGroup = knowledgeCategoryGroups.find((group) => group.title === activeKnowledgeGroupTitle) || knowledgeCategoryGroups[0];
  const groupTabs = knowledgeCategoryGroups
    .map(
      (group) => `
        <button class="knowledge-group-toggle ${group.title === activeGroup.title ? "active" : ""}" type="button" data-knowledge-group="${group.title}">
          <span>${group.title}</span>
          <small>${group.items.length}</small>
        </button>
      `,
    )
    .join("");
  const categoryTabs = activeGroup.items
    .map((item) => {
      const count = claims.filter((claim) => claimMatchesKnowledgeCategory(claim, item)).length;
      const key = getKnowledgeCategoryKey(item);
      return `
        <button class="stage-button ${activeKey === key ? "active" : ""}" type="button" data-knowledge-category-type="${item.type}" data-knowledge-category-value="${item.value}">
          <span>${count}</span>
          ${item.label}
        </button>
      `;
    })
    .join("");
  document.querySelector("#knowledge-stage-list").innerHTML = `
    <div class="knowledge-filter-row primary">${groupTabs}</div>
    <div class="knowledge-filter-row secondary">${categoryTabs}</div>
  `;
  syncKnowledgeFilterSummary();
}

function renderKnowledge() {
  const query = document.querySelector("#knowledge-query").value.trim().toLowerCase();
  const claims = getAllClaims().filter((claim) => {
    const matchesCategory = claimMatchesKnowledgeCategory(claim, activeKnowledgeCategory);
    const haystack = `${claim.object} ${claim.stance} ${claim.stage} ${claim.tags.join(" ")} ${claim.conclusion} ${claim.reasons.join(" ")} ${claim.creator}`.toLowerCase();
    return matchesCategory && (!query || haystack.includes(query));
  });

  document.querySelector("#knowledge-results").innerHTML =
    claims.length > 0
      ? claims.map(renderClaimCard).join("")
      : `<article class="result-card"><h3>暂无匹配观点</h3><p>换一个流程阶段、标签或关键词试试。</p></article>`;
  renderKnowledgeCategories();
}

document.addEventListener("click", (event) => {
  const navButton = event.target.closest(".nav-item");
  if (navButton) {
    setView(navButton.dataset.view);
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

  const knowledgeToggleButton = event.target.closest("#knowledge-filter-toggle");
  if (knowledgeToggleButton) {
    const expanded = knowledgeToggleButton.getAttribute("aria-expanded") === "true";
    setKnowledgeFilterExpanded(!expanded);
    return;
  }

  const stageButton = event.target.closest("[data-knowledge-stage]");
  if (stageButton) {
    const stageName = stageButton.dataset.knowledgeStage;
    const category =
      knowledgeCategoryGroups
        .flatMap((group) => group.items)
        .find((item) => item.type === "stageGroup" && item.stages?.includes(stageName)) || findKnowledgeCategory("all", "全部");
    activeKnowledgeCategory = category;
    activeKnowledgeGroupTitle = "按流程大类";
    renderKnowledge();
    setView("knowledge");
    return;
  }

  const knowledgeGroupButton = event.target.closest("[data-knowledge-group]");
  if (knowledgeGroupButton) {
    const groupTitle = knowledgeGroupButton.dataset.knowledgeGroup;
    activeKnowledgeGroupTitle = groupTitle;
    activeKnowledgeCategory = knowledgeCategoryGroups.find((group) => group.title === groupTitle)?.items[0] || findKnowledgeCategory("all", "全部");
    setKnowledgeFilterExpanded(true);
    renderKnowledgeCategories();
    renderKnowledge();
    return;
  }

  const categoryButton = event.target.closest("[data-knowledge-category-type]");
  if (categoryButton) {
    activeKnowledgeCategory =
      findKnowledgeCategory(categoryButton.dataset.knowledgeCategoryType, categoryButton.dataset.knowledgeCategoryValue) ||
      findKnowledgeCategory("all", "全部");
    renderKnowledge();
    setKnowledgeFilterExpanded(false);
    return;
  }

  const progressFilterButton = event.target.closest("[data-progress-filter]");
  if (progressFilterButton) {
    activeProgressFilter = progressFilterButton.dataset.progressFilter;
    renderProgress();
    return;
  }

  const videoPlatformButton = event.target.closest("[data-video-platform]");
  if (videoPlatformButton) {
    activeSourceFilter = null;
    activeVideoPlatform = videoPlatformButton.dataset.videoPlatform;
    activeVideoCreator = "全部";
    renderVideos();
    return;
  }

  const videoCreatorButton = event.target.closest("[data-video-creator]");
  if (videoCreatorButton) {
    activeSourceFilter = null;
    activeVideoCreator = videoCreatorButton.dataset.videoCreator;
    renderVideos();
    return;
  }

  const openIngestButton = event.target.closest("#open-ingest");
  if (openIngestButton) {
    if (openIngestButton.hidden) return;
    setIngestOpen(true);
    return;
  }

  const closeIngestButton = event.target.closest("#close-ingest");
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
    updateSourceButton.disabled = true;
    updateSource(updateSourceButton.dataset.updateSourceId)
      .catch((error) => setSourceMessage(`失败：${error.message}`, "error"))
      .finally(() => {
        updateSourceButton.disabled = false;
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
    douyinLoginButton.disabled = true;
    startDouyinLogin(douyinLoginButton.dataset.douyinLoginUrl)
      .catch((error) => setSourceMessage(`打开登录失败：${error.message}`, "error"))
      .finally(() => {
        douyinLoginButton.disabled = false;
      });
    return;
  }

  const updateAllSourcesButton = event.target.closest("#update-all-sources");
  if (updateAllSourcesButton) {
    updateAllSourcesButton.disabled = true;
    updateAllSources()
      .catch((error) => setSourceMessage(`失败：${error.message}`, "error"))
      .finally(() => {
        updateAllSourcesButton.disabled = false;
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
    renderVideos();
    return;
  }

  const progressRunButton = event.target.closest("#progress-process-pending");
  if (progressRunButton) {
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
    progressRetryButton.disabled = true;
    if (state === "缺链接") {
      setView("sources");
      setSourceMessage("这条视频缺链接，请先从来源页更新该博主作品。", "warn");
      progressRetryButton.disabled = false;
      return;
    }
    if ((video?.retryCount || 0) >= 3) {
      force = confirm(`该视频已重试 ${video.retryCount} 次，仍可能无法正确提取文案。确定继续从获取文案开始重试吗？`);
      if (!force) {
        progressRetryButton.disabled = false;
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
        progressRetryButton.disabled = false;
        progressRetryButton.textContent = "重试";
      });
    return;
  }

  const extractButton = event.target.closest("[data-extract-video-id]");
  if (extractButton) {
    const videoId = extractButton.dataset.extractVideoId;
    extractButton.disabled = true;
    extractButton.textContent = "提取中";
    postJson(`${API_BASE}/videos/${videoId}/extract`, {})
      .then(async (result) => {
        if (result.status !== "completed") throw new Error(result.status || "extract_failed");
        await loadApiData();
        selectedVideoId = videoId;
        renderAll();
        renderDetail();
        renderProgress();
        setView("detail");
      })
      .catch((error) => {
        extractButton.disabled = false;
        extractButton.textContent = "提取观点";
        alert(`提取失败：${error.message}`);
      });
  }
});

document.querySelector("#knowledge-query").addEventListener("input", renderKnowledge);
document.addEventListener("submit", (event) => {
  if (event.target !== ingestForm) return;
  event.preventDefault();
  saveVideoFromForm(ingestSubmitMode).catch((error) => {
    setIngestMessage(`失败：${error.message}`, "error");
  });
});
document.addEventListener("click", (event) => {
  const submitButton = event.target.closest("#ingest-form button[type='submit']");
  if (submitButton) {
    ingestSubmitMode = submitButton.dataset.mode || "save";
  }
});

document.addEventListener("keydown", (event) => {
  if (event.key !== "Enter" && event.key !== " ") return;
  const sourceFilterCard = event.target.closest("[data-source-filter-id]");
  if (!sourceFilterCard || event.target.closest("button, a")) return;
  event.preventDefault();
  applySourceFilter(sourceFilterCard.dataset.sourceFilterId, sourceFilterCard.dataset.sourceFilterName);
});

function renderAll() {
  renderOverview();
  renderSources();
  renderVideos();
  renderProgress();
  renderDetail();
  renderKnowledgeCategories();
  renderKnowledge();
}

setView(activeView, { updateHash: false });
renderAll();
enforceHashView();
window.requestAnimationFrame(enforceHashView);
window.addEventListener("DOMContentLoaded", enforceHashView);
window.addEventListener("popstate", syncViewFromHash);
window.addEventListener("hashchange", syncViewFromHash);
loadApiData();
