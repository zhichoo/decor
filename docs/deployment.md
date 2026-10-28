# Docker 部署与公开展示

## 两种使用方式

- 自建：每个人部署自己的应用与数据库，配置自己的模型 API Key，以管理员身份导入文案、提取知识，不共享作者的 Key、登录态或真实数据。
- 在线体验：[decor.zhichoo.com](https://decor.zhichoo.com)，Cloudflare 纯静态快照，访客仅浏览。没有登录、修改、删除、模型提取入口，也没有数据库或后端接口；不会收到作者的 Key 或浏览器登录态。

当前是单管理员应用，不是多租户 SaaS；不支持访客注册、各自保存 Key、隔离知识库。不要为了开放体验而允许匿名模型调用，否则费用和数据修改风险都会落在站点所有者身上。

## 一键启动

```bash
git clone https://github.com/zhichoo/decor.git
cd decor
./deploy.sh
```

需要 Docker Compose v2 和 `openssl`（用于本机生成随机密码）。首次构建下载 Python 依赖、Chromium 和 FFmpeg，可能较慢。镜像不含 ASR 权重、私人文案、数据库备份、API Key 或抖音登录态。

默认仅绑定 `127.0.0.1:4189`。远程服务器推荐通过 SSH 隧道进入管理页面：

```bash
ssh -L 4189:127.0.0.1:4189 user@your-server
```

然后打开本机 `http://127.0.0.1:4189/`，使用服务器 `.env.docker` 中的管理员密码登录。不要公开隧道或将管理端口转发至公网。

首次生成的 `.env.docker` 权限为 `0600`。修改后执行 `./deploy.sh` 重建/重建容器即可生效。不要在工单、截图、日志或 `docker compose config` 输出中泄露密钥。

| 配置 | 用途 |
| --- | --- |
| `ADMIN_PASSWORD` | 至少 16 字符；脚本默认生成 48 位随机十六进制密码 |
| `POSTGRES_PASSWORD` | 初始化数据库密码；默认随机生成；自定义时限用 URL 安全字符 |
| `DEEPSEEK_API_KEY` | 自己的 DeepSeek 官方 Key；为空时不能 AI 提取 |
| `DEEPSEEK_BASE_URL` | 默认 `https://api.deepseek.com`，不自动回退中转 |
| `DEEPSEEK_MODEL` | 默认 `deepseek-flash`，需要是接口实际支持的模型 |
| `DECOR_PORT` | 管理服务宿主机端口，默认 4189 |
| `DECOR_BIND` | 默认 `127.0.0.1`；不要不加保护地改为公网绑定 |
| `DECOR_PUBLIC_PORT` | 可选只读服务端口，默认 4190，仅绑定本机 |
| `PUBLIC_READ_ONLY` | 主服务是否只读，默认 false；独立 public 服务固定 true |
| `TRANSCRIPT_PROVIDER` | 默认 `local_asr`；外部转写使用 `transcriptgenerate` |
| `TRANSCRIPTGENERATE_*` | 外部转写凭据，与知识提取的 Key 分开配置 |
| `LOCAL_ASR_THREADS` | 本地 ASR 线程数，默认 3 |

网页切换转写提供方后，选择保存在持久化卷，优先于环境变量。已有文案可直接提取知识，无需先安装 ASR 模型。

## Cloudflare 静态公开版（推荐）

采用 Workers Static Assets，仅托管静态文件，不运行 Worker 脚本。浏览器在公开快照内完成搜索、分类、分页和详情查询；没有服务端写接口。无需给 Cloudflare 配置数据库连接或模型 API Key。

发布者需要已配置数据库连接的本地 Python 环境（例如已运行过 `./dev.sh`），以及 Node.js 22+。以下命令从当前本地数据库导出**有效来源、未删除视频、文案及其观点**：

```bash
./publish-public.sh --build-only       # 仅生成 .runtime/public-site，便于检查
npx --yes wrangler@4.154.0 login      # 使用自己的 Cloudflare 账号授权
./publish-public.sh                  # 重新导出并发布
```

**Fork / 自建者发布前必须修改 `wrangler.public.jsonc` 中的项目名和域名**，换成自己 Cloudflare 账号中处于生效状态的域名；不绑定自定义域名可删除 `routes`，使用自己的 `workers.dev` 地址。`decor.zhichoo.com` 是作者的公开站点，不是自建用户的默认发布目标。也可复制配置后通过 `DECOR_WRANGLER_CONFIG=你的配置文件 ./publish-public.sh` 指定。

Wrangler 使用账号授权发布静态资源，并为配置的自定义域名创建路由、DNS 和 HTTPS 证书。项目不包含 Worker 业务脚本，不绑定数据库或密钥；若出现同名 DNS 冲突，先核对现有用途，不要覆盖其他站点。

导出过程使用只读一致性事务，不修改业务数据库、不调用模型。生成目录被 Git 忽略；不会导出私有配置、来源备注、转写任务凭据、提取调用记录、原始错误或回收站记录。静态产物从 HTML 中移除管理入口，并拒绝客户端写请求；部署时也不存在可写 API。`?api=` 参数不能将公开版连接到其他后端。

**快照内容可被任何访客完整下载，包括公开的视频文案。** 发布前确认内容版权、隐私和分享范围。不要把敏感信息写进准备公开的文案或观点。以后在本地新增、修改或删除知识后，必须重新执行发布命令；本地删除不会自动撤回已发布快照，也无法撤回访客此前下载的副本。

上线核对：浏览器可以搜索、分类、翻页、查看文案和观点；没有登录、添加来源、设置、修改或删除入口；网络仅加载静态资源和快照 JSON，不请求 `/api`。对不存在的 `/api` 地址应返回 404/405，而不是进入管理服务。

## 可选：服务器实时只读展示

需要内容实时同步、愿意维护服务器时，可使用一套数据库、两个服务；这不是上面的静态公开版。管理服务留在本机，公开服务通过 `PUBLIC_READ_ONLY=true` 只读展示同一份知识。公开服务不注入管理员密码、模型 Key 或转写凭据，也不挂载浏览器登录卷。

```bash
./deploy.sh --profile public up -d --build
```

- 管理端：`http://127.0.0.1:4189/`，需要登录才能操作。
- 公开端：`http://127.0.0.1:4190/`，没有管理员登录入口；禁止所有写操作与模型调用。
- 两者读取同一个数据库，不复制知识卡。公开端统计可能有约 15 秒缓存延迟。

将最新版域名 DNS 指向服务器，用宿主机 Caddy / Nginx 转发到 **4190 而不是 4189**。Caddy 示例（将域名替换为自己的真实域名）：

```caddyfile
knowledge.your-domain.example {
    reverse_proxy 127.0.0.1:4190
}
```

需要域名可解析到服务器，80/443 可达，配置 TLS 与访问限速。使用其他反向代理也应启用 HTTPS；管理服务仍保持本机绑定。不要通过 `?readonly=1`、CSS 隐藏入口或用户可伪造的 Host / 请求头来实现权限隔离。

只有确认自己的域名确实指向只读服务后，才对外分享；不要将作者静态站的域名改指向管理服务。

上线核对：页面没有管理员登录、添加来源、设置、删除按钮；`GET /api/admin/session` 返回 `read_only: true`、`authenticated: false`；对 `/api/admin/login`、`/api/videos/任意ID/extract` 的 POST 应返回 403。确认已有内容可浏览、搜索、查看详情。

公开站点会公开已有视频文案与知识卡。发布前确认内容版权、隐私和分享范围；模型观点不等于事实核验或专业装修建议。当前使用 Python 内置 HTTP 服务，适合个人/小规模使用，仍需反向代理；高并发、多实例任务调度和登录防暴力破解需另行建设。

## 视频文案与本地 ASR

默认不会在启动时下载大模型或消耗模型额度。需要本地转写时：

```bash
./deploy.sh exec app python scripts/setup_local_asr.py
```

模型保存在 `app-runtime` 持久化卷。管理员在设置中检测本地服务后使用。

镜像包含 Chromium、FFmpeg 与虚拟显示，能运行浏览器采集代码，但**服务器虚拟显示不是可交互的抖音扫码登录网页**。当前没有远程浏览器桌面；网页「登录抖音」在容器里打开的窗口不会出现在访客电脑。不要承诺一键自动登录。需有效会话、验证码或平台风控时，改用手动文案入库/自行配置外部转写，或在有桌面的本机使用 `./dev.sh` 管理采集。不要公开 VNC、浏览器调试端口、Cookies 或登录目录。

API 转写独立计费，并非 DeepSeek API 的一部分。容器不自动切换付费转写、不自动复制本机登录态。

## 备份、迁移、恢复

容器部署默认空库，作者现有数据不会随 GitHub 或镜像发布。备份包含文案、观点、软删除记录，视为私有文件。

```bash
mkdir -p backups
chmod 700 backups
(umask 077; ./deploy.sh exec -T db pg_dump -U decor -d decor -Fc > backups/decor.dump)
```

还应单独保存私有 `.env.docker`，并按需备份 ASR / 浏览器数据卷；不要上传公共仓库。

从当前本地实例迁移时，先执行 `./dev.sh backup /absolute/path/decor.dump`。在**尚未启动应用、业务表为空**的新 Docker 数据库恢复：

```bash
./deploy.sh up -d db
./deploy.sh exec -T db pg_restore -U decor -d decor --no-owner --no-acl --exit-on-error < /absolute/path/decor.dump
./deploy.sh
```

不要对已有数据的数据库重复恢复，也不要使用 `--clean` 清空现有库。应用启动会验证表结构并添加兼容的可空任务字段，不自动填演示数据、不重置已有业务记录。旧版本不兼容结构会明确失败，不自动破坏性重建。

如果管理端仍运行在本机而公开服务部署到远程服务器，数据库不会自动同步。需要明确选择定期备份恢复的只读快照，或把管理端与公开端一起迁移到服务器；不要直接将本机 PostgreSQL 端口暴露公网。

## GitHub 发布镜像

仓库已有 `.github/workflows/docker.yml`：手动运行 Docker Image 工作流，或推送 `v*` 版本标签，构建并推送 `ghcr.io/zhichoo/decor`。目前发布 `linux/amd64` 镜像；Apple Silicon 可本地构建，或显式指定兼容平台使用模拟运行。

首次发布后需在 GitHub Packages 将包可见性设为 Public，匿名用户才能拉取。只有源码公开并不代表镜像包自动公开。工作流不需要作者的模型 Key、数据库密码或浏览器凭据，只使用 GitHub 提供的仓库发布令牌。

**在工作流首次成功发布前，使用本地构建，不要假定 GHCR 已有镜像。**发布后，在 `.env.docker` 设置 `DECOR_IMAGE=ghcr.io/zhichoo/decor:版本号`（推荐固定版本），然后：

```bash
./deploy.sh pull app
./deploy.sh up -d --no-build app
# 如需公开服务，同样拉取并启动该镜像：
./deploy.sh --profile public pull public
./deploy.sh --profile public up -d --no-build public
```

版本更新前先备份；执行 `./deploy.sh` 不带参数默认走源码构建。当前没有内置用户注册与云平台真正的「Deploy」按钮，所说的一键部署是克隆仓库后运行一条脚本。
