# 装修知识库

采集装修视频、保存文案、提取观点并按装修阶段和主题检索的个人知识库。前端与 Python API 由同一个服务提供，PostgreSQL 18 保存数据。

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

AI 和转写配置参考 [backend/config.example.json](backend/config.example.json)，填入 `backend/config.local.json` 后重启。主要参数为 `DEEPSEEK_API_KEY`、`DEEPSEEK_BASE_URL`、`DEEPSEEK_MODEL`、`TRANSCRIPTGENERATE_TOKEN`，以及需要重新登录转写服务时使用的邮箱/密码。缺少外部服务配置时，已有数据浏览、检索和人工文案入库仍可使用。

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
dev.sh                统一入口
```

项目通过 Git subtree 保留原 `decor-backend` 和 `decor-web` 的提交历史。本仓库仅保存源码和数据库结构，真实数据、密码、转写账号、浏览器登录状态与运行日志均不提交。

服务默认仅监听本机地址。转写失败保留旧文案、观点事务替换、完整写接口鉴权及队列持久化仍属于后续开发事项；当前合并主要完成运行环境、数据库恢复和前后端统一入口。
