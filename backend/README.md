# 后端

本目录属于 [decor 合并项目](../README.md)。Python API、抖音浏览器采集、第三方转写和 AI 观点提取代码位于此处。

在仓库根目录运行 `./dev.sh` 即可同时启动后端与前端，本地数据使用持久化 PostgreSQL 18。配置存放于本目录的 `config.local.json`，该文件不提交。

需要单独启动 API 时，先准备已初始化数据库，再设置 `DATABASE_URL`，运行 `python server.py 4189`。通过 `STATIC_ROOT` 可指定静态页面目录。
