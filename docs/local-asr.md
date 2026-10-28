# 本地 ASR 接入与真实视频回放

2026-10-15，项目 `/Users/villow/myProject/github/decor`，仅本地修改，未提交或推送。
运行地址 http://127.0.0.1:4189/ 。

## 实施

- 本机私有配置已切换 `TRANSCRIPT_PROVIDER=local_asr`、`LOCAL_ASR_THREADS=3`，取消原外部服务 120 秒额度等待。原配置备份 `.runtime/asr/config-before.local.json`，0600，不输出凭据。
- 使用 sherpa-onnx 1.12.40 + SenseVoiceSmall INT8 + Silero VAD，CPU 单任务、跨进程文件锁；每段最长约 25 秒，合并为文案。FFmpeg 使用 imageio-ffmpeg 自带二进制。
- 复用现有抖音浏览器登录，下载请求限制官方媒体域名、HTTPS、重定向域名、512 MiB 和耗时；只取匹配原视频 ID 的媒体数据。最多处理 2 小时音频，超限明确失败，不静默截断。
- 临时文件自动清理，模型固定在 `.runtime/asr/models`；安装脚本对模型、词表、VAD 校验 SHA-256，只下载 INT8 所需文件。INT8 模型约 228 MiB。
- 已有文案不重录；失败保留旧文案和知识卡；人工编辑优先；本地任务可重跑。本地模式不调用外部转写服务，不自动提取知识卡。未完成旧外部任务账本不会被隐式覆盖，也不自动续查。
- 前端区分本地失败后的“重试本地转写”和旧服务“续查文案”。原人工保存、知识卡提取入口保留。

## 最近五条真实测试

所有视频均实际下载成功；下表耗时为缓存视频上的音轨解码、模型加载、VAD 与 CPU 转录，非纯神经网络推理时间，不含视频下载。

| 视频 | 音轨时长 | 本地处理耗时 | ASR worker 峰值 RSS | 原/本地文案字数 | 与旧文案归一化文本相似度 |
|---|---:|---:|---:|---:|---:|
| 木门选购 | 159.41 秒 | 8.13 秒 | 510.8 MiB | 869 / 862 | 96.12% |
| 装修省钱 | 548.94 秒 | 16.33 秒 | 620.9 MiB | 3014 / 2943 | 92.16% |
| 全屋净水 | 272.83 秒 | 10.17 秒 | 618.5 MiB | 1376 / 1349 | 93.43% |
| 装修停工节点 | 162.70 秒 | 5.78 秒 | 579.8 MiB | 925 / 909 | 95.84% |
| 弧形踢脚线 | 48.55 秒 | 2.23 秒 | 594.2 MiB | 306 / 306 | 89.82% |

总音轨 1192.44 秒，处理共 42.65 秒。本机 Apple Silicon、3 线程，不代表 4c8g VPS 的速度。RSS 仅为 ASR worker，不是整个网站、数据库、浏览器和系统的总内存。

额外从抖音链接执行踢脚线视频完整流程：下载 + 解码 + ASR 9.23 秒，输出 306 字，worker 峰值 623.1 MiB。视频下载仍需要网络和有效平台访问条件；“本地 ASR”不等于无须处理视频源获取。

旧服务的文案本身也有错字，不是人工真值；相似度不能当作准确率。样本中本地仍有“踢角线/铁脚线”等同音误识别，旧文案也有“玄武羊角”等错误，不宣称全面优于旧服务。未擅自做 LLM 改写或覆盖原稿。

## 数据与验证

- 重启服务后 `running=true, ready=true`。
- 最近五条真实 HTTP 转写入口全部返回 `preserved_existing=true`，仍为 869、3014、1376、925、306 字，未重复转录或调用付费服务。
- 视频、知识卡、提取记录全部原字段逐表 SHA-256 在测试前、测试后、重启与真实 HTTP 验证后完全一致。
- 完整测试 97 项通过，含本地 provider 路由、失败保护、人工编辑保护、并发仅运行一次、HTTP 管理员鉴权与重复点击、旧付费任务保护；真实 SenseVoice 模型落库使用隔离临时 PostgreSQL，不写业务库。
- Python 编译、JS 语法检查、`git diff --check` 通过。保留此前未提交改动，没有恢复或覆盖无关修改。

## 产物

- `backend/local_asr.py`：受限下载、音轨处理、VAD/识别、跨进程锁。
- `scripts/setup_local_asr.py`：模型安装及完整性验证。
- `scripts/benchmark_local_asr.py`：最近已有文案视频的只读回放与数据不变校验。
- `.runtime/asr/benchmark/report.json`：五条真实结果、时长、内存、参考相似度。
- `.runtime/asr/benchmark/*.json` 与 `*.original.txt`：本地文案/分段与原稿独立副本。
- `.runtime/asr/benchmark/live-check.json`、`live-full-pipeline.json`：重启后验证与完整链路结果。
- `.runtime/asr/tests.log`：测试日志。
- `README.md`：安装、迁移至 Linux、配置、使用和已知限制。

当前仅支持抖音标准视频链接的网页获取入口；独立 worker 可识别本地音视频文件。没有做逐字字幕对齐；部署多副本需要共享调度；无显示环境服务器需提前准备 Playwright Chromium 和必要的浏览器登录配置。

## 网页设置与健康检测（2026-10-15 后续更新）

左侧底部新增“设置”，可选 API 或本地 ASR，仅管理员可修改或执行检测。
API 沿用现有 TranscriptGenerate 配置。切换只更新默认路由，不创建转录任务、不消耗额度。
本地模式在保存前执行独立 worker 的 `--health-check`：FFmpeg 可执行检测、SenseVoice 模型加载、
实际 CPU 推理及 VAD 模型加载。它是按需启动的 worker，不存在需要另启的常驻 HTTP 服务。
检测失败、超时或 worker 正忙时不启用本地模式、不回退、不改变原选择；页面展示原因。
检测不验证抖音登录或视频下载权限。

配置原子保存至 `backend/transcription-settings.local.json`（0600、Git 忽略），
优先于启动配置中的 `TRANSCRIPT_PROVIDER`，立即生效且重启保留。原私有账号和密钥配置未改写。
已保存文案不重录，执行中的任务保持原路由；未核对的旧 API 账本不会被本地转录覆盖。

网页验收记录位于 `.runtime/asr/settings-ui/report.json`，包括真实本地检测、API 切换、
模拟检测失败后保持 API、实际检测后切回本地、刷新保留选择、未登录禁用和手机无横向溢出。
截图为同目录 `desktop.png`、`mobile.png`、`local-failure.png`。
验收前后视频、知识卡、提取记录全部字段哈希一致，无真实外部转录请求、无自动观点提取。
新增设置及路由测试、完整回归日志位于 `.runtime/asr/settings-tests.log`。
