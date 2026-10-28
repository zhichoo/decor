# 装修知识库

采集装修视频、保存文案、提取观点并按装修阶段和主题检索的个人知识库。前端与 Python API 由同一个服务提供，PostgreSQL 18 保存数据。

## 在线体验

**[在线预览：decor.zhichoo.com](https://decor.zhichoo.com)**。Cloudflare 托管的纯静态公开版，支持分类、搜索和详情浏览；没有管理员登录、修改、删除、采集或提取功能，也不连接数据库和后端 API。

公开版是发布时的知识库快照，不会自动同步本地变化；本地修改或删除后，需要重新发布才能更新。导出与发布命令见 [静态公开版部署](docs/deployment.md#cloudflare-静态公开版推荐)。

想用自己的 API Key 采集、整理知识，请自建独立实例；在线体验站不接收访客密钥。源码仓库：[zhichoo/decor](https://github.com/zhichoo/decor)。

## Docker 一键部署

需要 Docker Engine / Docker Desktop 与 Docker Compose v2，首次构建需要联网。无需在宿主机安装 Python。建议本地 ASR 使用至少 4 核 / 8 GB；只做文案知识提取不需要安装 ASR 模型。

```bash
git clone https://github.com/zhichoo/decor.git
cd decor
./deploy.sh
```

脚本首次生成私有 `.env.docker` 和随机数据库、管理员密码，启动应用与 PostgreSQL，并初始化空库。默认打开 **http://127.0.0.1:4189/**；管理员密码见 `.env.docker` 的 `ADMIN_PASSWORD`。

编辑 `.env.docker`，填写自己的 `DEEPSEEK_API_KEY`，然后执行 `./deploy.sh` 应用配置。每个实例使用各自的 Key 和额度；Key 只进入服务端，不会发给网页访客，也不应提交 Git。无需 Key 也能浏览已有内容和手动保存文案，AI 提取需要有效 Key。

登录管理员 → 视频来源 → 添加来源 / 手动文案入库 → 提取观点。自动获取视频文案还需要单独准备转写服务或本地 ASR，**只有模型 API Key 并不能解决抖音登录、验证码与视频访问权限**。

```bash
./deploy.sh ps                       # 查看状态
./deploy.sh logs --tail=100 app       # 查看日志
./deploy.sh down                     # 停止，不删除数据卷
./deploy.sh                          # 更新代码后重新构建并启动
```

数据库、ASR 模型/设置和浏览器配置分别持久化到 `decor-deploy_*` 命名卷；不会使用或覆盖 `./dev.sh` 的本地数据卷。不要使用 `down -v`，也不要在数据库初始化后随意修改 `POSTGRES_PASSWORD`。详细配置、公开站点、HTTPS、迁移、备份和 GitHub 镜像发布见 **[Docker 部署指南](docs/deployment.md)**。

## 本地启动

需要 Docker Desktop、Python 3.12 或更新版本；推荐安装 [uv](https://docs.astral.sh/uv/)。抖音采集还需要本机 Google Chrome。

```bash
./dev.sh
```

首次启动会创建本地配置、安装 Python 依赖、启动数据库并初始化空库。服务在后台运行，终端关闭后继续保留。默认访问：**http://127.0.0.1:4189/**。网页和 `/api` 使用同一个地址，无需单独启动前端。

```bash
./dev.sh status
./dev.sh stop
./dev.sh start
```

停止不会删除数据库卷。应用日志在 `.runtime/server.log`。数据库监听 `127.0.0.1:15439`，数据保存在 Docker 命名卷 `decor_postgres-data`。

## 配置

启动脚本会生成 `.env` 和 `backend/config.local.json`，这两个文件仅保存在本机，并设为只有当前用户可读写。管理员密码保存在 `backend/config.local.json` 的 `ADMIN_PASSWORD` 字段。

如需修改应用端口，修改本地配置中的 `PORT` 并重启。数据库端口通过 `.env` 的 `DECOR_DB_PORT` 设置。启动脚本统一管理本地数据库连接；直接运行 API 时可以使用环境变量 `DATABASE_URL` 指定其他数据库。

AI 配置参考 [backend/config.example.json](backend/config.example.json)，填入 `backend/config.local.json` 后重启。主要参数为 `DEEPSEEK_API_KEY`、`DEEPSEEK_BASE_URL`、`DEEPSEEK_MODEL`。缺少外部服务配置时，已有数据浏览、检索和人工文案入库仍可使用。

默认使用 DeepSeek 官方接口 `https://api.deepseek.com` 和官方模型名 `deepseek-flash` 提取知识卡，配置沿用 `DEEPSEEK_*` 字段。请使用官方 API Key，不要混用中转密钥；不会自动回退到中转服务。密钥只保存在私有本地配置中。超时或读取中断后保留现有内容，由管理员手动重试。

## 备份与恢复

```bash
./dev.sh backup
./dev.sh backup /absolute/path/decor.dump
```

默认备份保存在 `.runtime/backups/`。备份包含业务表结构、全部数据以及软删除记录。

恢复必须在应用停止且目标数据库为空时进行；脚本会拒绝覆盖已有表。首次迁移时，先恢复再启动：

```bash
./dev.sh restore /absolute/path/decor.dump
./dev.sh start
```

数据库初始化和演示数据说明见 [docs/database.md](docs/database.md)。演示数据不自动写入；需要时执行：

```bash
.venv/bin/python backend/seed_data.py
```

## 项目结构

```text
backend/              Python API、抖音采集、模型提取、转写集成
web/                  静态管理界面，index.html 为最新界面
db/schema.sql         可从零初始化的数据库结构
scripts/init_db.py    初始化检查：已有数据保持不变，部分表存在时拒绝操作
scripts/dev.py        启动、停止、状态、备份和恢复
compose.yaml          本地 PostgreSQL 18 与持久化数据卷
compose.deploy.yaml   Docker 完整部署，可选独立公开只读服务
Dockerfile            非 root 应用镜像（Python、Chromium、FFmpeg）
deploy.sh             一键部署与 Compose 命令入口
publish-public.sh     导出只读快照并发布到 Cloudflare
wrangler.public.jsonc 纯静态资源托管与自定义域名配置
dev.sh                统一入口
```

项目通过 Git subtree 保留原 `decor-backend` 和 `decor-web` 的提交历史。本仓库仅保存源码和数据库结构，真实数据、密码、转写账号、浏览器登录状态与运行日志均不提交。

文案保存后自动识别软性推广，推广视频打上标签，不自动提取观点；判断不确定或识别失败时暂缓自动提取，保留已有内容。管理员仍可人工提取。识别依据、模型调用与批量补齐方式见 [docs/advertising.md](docs/advertising.md)。

服务默认仅监听本机地址。转写失败保留旧文案和知识卡；知识替换、视频删除在事务中完成。提取结果必须有可核对的文案原句，空结论、伪造引用、无依据的数字和严重口头禅会被拒绝；新结果全部不合格时保留旧卡。删除使用回收站，备份也包含已删除记录。

删除视频会先弹出确认窗口，可选择是否同时删除该视频已提取的观点（默认勾选）。取消勾选后，视频移入回收站，观点仍保留在知识库中。点击取消或按 Esc 不会执行删除。

DeepSeek Flash / v4 的结构化提取默认关闭思考模式，避免推理耗尽输出额度后没有 JSON 正文。如需开启，可在本地配置设置 `DEEPSEEK_THINKING=enabled`、`DEEPSEEK_REASONING_EFFORT=low` 和 `DEEPSEEK_MAX_OUTPUT_TOKENS`。

来源页的“更新所有来源”会逐个处理启用来源并报告成功、失败和跳过情况。抖音主页采集依赖浏览器登录：先在来源页点击“登录抖音”，完成登录后检查登录态，再更新来源。人工文案入库和已有视频转写不依赖这个浏览器登录。

所有抖音来源采集统一跳过置顶作品，置顶不占采集数量；例如选择 5 条时，会从非置顶作品中按发布时间选取。已手动删除的视频不会因来源更新重新恢复；单个来源和全部来源的更新结果均显示跳过数量、视频标题及“此前已删除，不自动恢复”的原因，并附上原删除原因（如有）。需要恢复时请在回收站明确操作。该规则不回溯删除已经入库的置顶作品。

管理员明确要求单次导入置顶作品时，可向批量入库接口 `/api/videos/batch-collect` 传入布尔值 `include_pinned: true` 并提供已确认归属的作品列表。此例外只对该次请求生效，不改变来源后续更新规则，且仍跳过已删除视频。

视频来源和博主筛选的数量按全部有效视频统计；选择某位博主后，其他博主仍保留可选。知识库分类数字按全部有效知识卡统计，切换分类或搜索不会改变其他分类的数字。

视频详情中的“编辑文案”支持手动修改并保存，也可以给没有文案的视频补写文案。保存会保留现有知识卡和提取记录；需要重新生成卡片时，再点击“提取观点”。

来源新增/修改、视频导入（包括只提供手动文案、不提取观点）、分享链接修改、来源更新、视频重试、文案保存、转写、观点提取、自动队列和打开抖音登录窗口需要先登录管理员。所有 POST 接口默认要求管理员会话，仅登录和退出接口公开；未登录、会话无效或过期时，在读取请求体、访问数据库或调用模型之前拒绝请求。未登录时管理按钮、添加来源以及“已删除”“设置”菜单直接隐藏；登录后恢复显示，退出后立即隐藏并关闭添加来源面板。访客直接访问管理页面链接会回到流程总览。隐藏入口不代替权限校验。已有数据浏览、搜索和详情查看无需登录。

视频详情支持管理员手动编辑和保存文案；保存后保留已有知识卡。点击“提取观点”或“重新提取观点”会使用已保存文案生成知识卡，不重新转写视频。

AI 请求默认等待最多 300 秒，连接超时为 15 秒，遇到限流、临时服务错误或明确的连接建立失败最多自动重试一次。超时和空响应不自动重复提交；可在详情页手动重试。鉴权和余额错误也不会自动重试。可在 `backend/config.local.json` 中设置 `DEEPSEEK_TIMEOUT_SECONDS`、`DEEPSEEK_CONNECT_TIMEOUT_SECONDS` 和 `DEEPSEEK_MAX_RETRIES`，修改后重启应用。提取失败时保留文案和已有知识卡。

后台队列的运行状态仍保存在内存中，重启后需要手动重新启动队列。公网部署务必使用 HTTPS；公开展示推荐静态快照，管理服务只通过本机或 SSH 隧道访问。

## 本地 ASR（CPU，无需独显）

使用 `sherpa-onnx + SenseVoiceSmall INT8 + Silero VAD`，与知识卡 AI 提取独立。
适合以中文口播为主的视频；支持普通话、粤语、英语、日语、韩语。4 核 8 GB
服务器先使用 3 个推理线程、单任务处理；实际速度取决于 CPU，不能照搬 Mac 测试数据。

```bash
uv pip install --python .venv/bin/python -r backend/requirements.txt
.venv/bin/python scripts/setup_local_asr.py
```

模型默认在 Git 忽略的 `.runtime/asr/models/`，可通过 `LOCAL_ASR_MODEL_DIR` 指定持久化目录。
下载 Hugging Face 较慢时，安装脚本可设置 `LOCAL_ASR_DOWNLOAD_BASE` 为对应仓库的可信镜像
`https://hf-mirror.com/csukuangfj/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17/resolve/main`。
只需提前下载模型；转录本身不访问外部 ASR 或 LLM。首次安装依赖可能需要联网下载 FFmpeg。

在 `backend/config.local.json` 设置后重启：

```json
{
  "TRANSCRIPT_PROVIDER": "local_asr",
  "LOCAL_ASR_THREADS": 3
}
```

管理员继续使用视频详情页的“获取文案”。流程为下载视频、FFmpeg 转为 16 kHz 单声道、
VAD 切分、CPU 识别和合并；保存来源为 `LocalASR/SenseVoiceSmall-int8/task:...`。
已有文案默认直接保留，不重新识别、不自动提取知识卡；失败不覆盖旧文案或知识卡。
本地任务可安全重跑。未完成的旧外部服务任务会保留账本并阻止隐式切换；需先核对原任务，
不会自动续查、创建外部任务或回退到付费服务。

本地 ASR 视频入口当前仅支持抖音标准视频链接，下载复用现有抖音浏览器登录配置。
服务器需要安装 Playwright Chromium：`.venv/bin/python -m playwright install --with-deps chromium`；
没有 Chrome 时会自动使用 Playwright Chromium。需要有效登录时，应通过已有登录流程准备浏览器
配置，不能保证无登录、验证码或平台风控时仍可下载。不要同时打开同一浏览器配置目录。
`LOCAL_ASR_BROWSER_PROFILE` 可指定专用登录配置。**本地识别不等于视频获取离线可用。**

同一项目目录下通过跨进程文件锁保证仅一个模型工作，默认最多下载 512 MiB 视频、处理 2 小时音频；
超限明确失败，不静默截断。临时音视频任务结束自动清理。部署多副本时仍需共享调度/队列；
当前不提供逐字字幕对齐，VAD 段时间仅作参考。

独立文件识别与只读回放（结果不写业务数据库）方式：

```bash
.venv/bin/python backend/local_asr.py --media-file /absolute/path/video.mp4
.venv/bin/python scripts/benchmark_local_asr.py --limit 5
```

回放最近五条已有文案的视频，结果、旧文案副本、耗时/峰值内存与数据校验报告保存在
`.runtime/asr/benchmark/`。文本相似度只是与旧服务输出的对比，不是人工标注的识别准确率。


### 网页切换 API / 本地转写

左侧导航底部的“设置”仅在管理员登录后显示，支持即时切换 API 或本地 ASR。
API 沿用现有 TranscriptGenerate 接口和账号配置，不会在切换时创建任务或消耗转录额度。
本地模式点击“检测并切换为本地”后，后端会执行真实的模型加载、CPU 推理、VAD 加载和
FFmpeg 可执行检测；失败或 worker 正忙时不切换，保留原选择。也可单独点击“检测本地服务”。
本地 worker 按需启动，不要求另启一个常驻 HTTP 服务；检测不验证抖音登录或视频下载权限。

选择保存在 Git 忽略的 `backend/transcription-settings.local.json`（0600），原子写入，
优先于 `TRANSCRIPT_PROVIDER`，无需重启且重启后保留。删除此文件后恢复环境变量/本地配置的默认方式。
仅改变后续任务，已有文案不重录、执行中的任务不改道；待核对的旧 API 任务不会被本地任务覆盖。
本地失败后可以明确切到 API 重试，但不会自动回退；API 账号与额度仍需自行保证有效。
