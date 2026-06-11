# 装修知识库 Backend

只提供 API、采集队列、文案提取和数据库访问。

## 启动

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp config.example.json config.local.json
.venv/bin/python server.py 4189
```

默认只开放 API：`http://127.0.0.1:4189/api/...`。

如需临时托管 Web 静态页面：

```bash
STATIC_ROOT=../web .venv/bin/python server.py 4189
```

## 配置

真实密钥写入 `config.local.json`，该文件不会提交。
