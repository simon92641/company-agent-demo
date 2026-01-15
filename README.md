# Company Agent Demo — RAG over Company Websites (Ollama + FastAPI)

<p align="center">
  <img src="https://skillicons.dev/icons?i=python,fastapi,html,css,js,bash,git,github,linux" />
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.10%2B-blue?logo=python&logoColor=white" />
  <img src="https://img.shields.io/badge/FastAPI-ready-009688?logo=fastapi&logoColor=white" />
  <img src="https://img.shields.io/badge/Ollama-local%20LLM-black" />
  <img src="https://img.shields.io/badge/RAG-embeddings%20%2B%20citations-orange" />
  <img src="https://img.shields.io/badge/Streaming-SSE-orange" />
</p>

<p align="center">
  <b>English</b> | <a href="#%E4%B8%AD%E6%96%87">中文</a>
</p>

A productizable RAG demo: **ingest public company websites → build an index → ask questions with citations**.

> Notes for the public repo: generated data (raw HTML / extracted pages / vectors / debug logs) and secrets are intentionally excluded via `.gitignore`.

---

## Demo

> Add your own assets:
>
> - Screenshot: `assets/screenshot.png`
> - GIF (optional): `assets/demo.gif`

![Web Demo Screenshot](assets/screenshot.png)

<!-- Optional -->
<!-- ![Demo GIF](assets/demo.gif) -->

---

## Features

- **Company-scoped knowledge base** (one index per `companies/<slug>`)
- **Multilingual answers** (auto language selection)
- **Citations + deep links** (Sources with Text Fragments when supported)
- **API key auth** via `X-API-Key`
- **Web UI** + **SSE streaming**
- Optional: **FAQ cache** (Quick Questions)

---

## Quickstart

### Prerequisites

- Python 3.10+
- Ollama running locally

### Run

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Pull models (adjust to your preference)
ollama pull qwen3:8b
ollama pull bge-m3:latest

# Build index for an example company
python tools/build_index.py acme

# Start the API server
uvicorn app.server:app --reload --port 8000
```

Open the web demo:

```text
http://localhost:8000/
```

---

## Configuration

Configuration priority:

1. Environment variables
2. `config.json`
3. Defaults in `app/config.py`

**Recommended for public repos**:

- Keep `config.json` / `.env` **local only** (already in `.gitignore`).
- Commit an example template: `config.example.json` or `.env.example`.

Example `config.example.json`:

```json
{
  "OLLAMA_BASE_URL": "http://localhost:11434",
  "LLM_MODEL": "qwen3:8b",
  "EMBED_MODEL": "bge-m3:latest",
  "API_KEY": "YOUR_LONG_RANDOM_KEY"
}
```

Auth behavior:

- If `API_KEY` is empty, auth is disabled.
- If non-empty, send `X-API-Key: <API_KEY>`.

---

## Ingestion Pipeline

One-command onboarding: ingest public pages → index → (optional) generate FAQ.

```bash
python scripts/ingest_company.py \
  --slug acme \
  --name "Acme" \
  --website "https://acme.example.com" \
  --seed "https://acme.example.com" \
  --max-pages 10 \
  --gen-faq true
```

Notes:

- You can pass `--seed` multiple times.
- Default: same-domain only; polite crawling with a delay.

<details>
<summary><b>Crawling strategy (details)</b></summary>

- URL discovery order: `robots.txt sitemap` → common sitemap paths → HTML sitemap → RSS → BFS expansion
- Language filtering: default keep English + Simplified Chinese; skip other locales
- JS fallback: if `requests` content is too short or site is SPA-like, use Playwright rendering (optional)

</details>

---

## Repo Layout

```text
company-agent-demo/
  app/                 # FastAPI service + RAG pipeline
  tools/               # Index utilities (e.g., build_index.py)
  scripts/             # Ingestion + reindex scripts
  static/              # Web UI
  companies/
    _example/           # (recommended) tiny sample for public repo
  requirements.txt
  README.md
  .gitignore
```

Generated artifacts (kept local; ignored by git):

- `companies/**/raw/` (raw HTML)
- `companies/**/extracted/` (cleaned text)
- `companies/**/rag/` (vectors / index metadata)
- `**/crawl_debug*.json`, logs, etc.

---

## API Examples

<details>
<summary><b>Health check</b></summary>

```bash
curl http://localhost:8000/health
```

</details>

<details>
<summary><b>Chat (with API key)</b></summary>

```bash
curl -H "X-API-Key: YOUR_LONG_RANDOM_KEY" \
  "http://localhost:8000/chat?company=acme&q=What%20does%20the%20company%20do%3F"
```

</details>

<details>
<summary><b>SSE streaming</b></summary>

```bash
curl -H "X-API-Key: YOUR_LONG_RANDOM_KEY" \
  -X POST "http://localhost:8000/chat?company=acme&q=Give%20me%20a%20summary&stream=1"
```

</details>

---

## Citations (Text Fragments)

Sources may return a deep link like:

```text
https://example.com/page#:~:text=<snippet>
```

When supported by the browser, it highlights the matched snippet and scrolls to it.

---

## Troubleshooting

- **“Index not found”** → run `python tools/build_index.py <company>` first.
- **Ollama not running / model missing** → start Ollama and `ollama pull ...`.
- **Auth errors** → check `API_KEY` and request header `X-API-Key`.
- **Empty answers / no citations** → confirm ingestion succeeded and pages were extracted.

---

## License

TBD.

---

# 中文

<p align="center">
  <a href="#company-agent-demo--rag-over-company-websites-ollama--fastapi">English</a> | <b>中文</b>
</p>

一个可产品化的 RAG Demo：**导入公司公开网页 → 建索引 → 带引用问答**。

> 公开仓库说明：生成数据（raw HTML / 抽取文本 / 向量 / debug/log）与敏感配置会被 `.gitignore` 过滤，不会提交。

---

## 演示

> 建议你放入：
>
> - 截图：`assets/screenshot.png`
> - 动图（可选）：`assets/demo.gif`

![Web Demo Screenshot](assets/screenshot.png)

<!-- 可选 -->
<!-- ![Demo GIF](assets/demo.gif) -->

---

## 功能亮点

- **公司维度知识库**（每个 `companies/<slug>` 一套索引）
- **多语言自动回复**（根据问题自动选择语言）
- **引用编号 + 深链跳转**（Sources 支持 Text Fragments 时可定位命中段落）
- **API Key 鉴权**：请求头 `X-API-Key`
- **网页 UI** + **SSE 流式输出**
- 可选：**FAQ 缓存**（Quick Questions）

---

## 从零开始运行

### 依赖

- Python 3.10+
- 本地 Ollama

### 运行

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 拉取模型（可按需替换）
ollama pull qwen3:8b
ollama pull bge-m3:latest

# 为示例公司构建索引
python tools/build_index.py acme

# 启动服务
uvicorn app.server:app --reload --port 8000
```

打开网页 Demo：

```text
http://localhost:8000/
```

---

## 配置说明

配置优先级：

1. 环境变量
2. `config.json`
3. `app/config.py` 默认值

公开仓库推荐做法：

- `config.json` / `.env` 只保留在本地（已在 `.gitignore` 中）。
- 提交 `config.example.json` 或 `.env.example` 作为模板。

示例 `config.example.json`：

```json
{
  "OLLAMA_BASE_URL": "http://localhost:11434",
  "LLM_MODEL": "qwen3:8b",
  "EMBED_MODEL": "bge-m3:latest",
  "API_KEY": "YOUR_LONG_RANDOM_KEY"
}
```

鉴权：

- `API_KEY` 为空：不启用鉴权。
- `API_KEY` 非空：请求需带 `X-API-Key: <API_KEY>`。

---

## 公司导入流水线（Onboarding Pipeline）

一键导入公开网页 → 建索引 →（可选）生成 FAQ：

```bash
python scripts/ingest_company.py \
  --slug acme \
  --name "Acme" \
  --website "https://acme.example.com" \
  --seed "https://acme.example.com" \
  --max-pages 10 \
  --gen-faq true
```

说明：

- `--seed` 可多次传入（多个入口页面）。
- 默认同域抓取，并带频率限制。

<details>
<summary><b>抓取策略（展开查看）</b></summary>

- URL 自动发现顺序：`robots.txt sitemap` → 常见 sitemap → HTML sitemap → RSS → BFS 扩散
- 语言过滤：默认只抓英文 + 简体中文（其它语言版本跳过）
- JS 兜底：站点偏 SPA / 内容过短时可用 Playwright 渲染抓取（可选）

</details>

---

## 目录结构

```text
company-agent-demo/
  app/                 # FastAPI 服务 + RAG 流水线
  tools/               # 建索引工具（build_index.py 等）
  scripts/             # 导入/重建脚本
  static/              # 网页 UI
  companies/
    _example/           #（推荐）公开仓库只保留极小示例
  requirements.txt
  README.md
  .gitignore
```

本地生成物（不提交）：

- `companies/**/raw/`（原始 HTML）
- `companies/**/extracted/`（清洗后的正文）
- `companies/**/rag/`（向量/索引元数据）
- `**/crawl_debug*.json`、日志等

---

## 接口调用示例

<details>
<summary><b>健康检查</b></summary>

```bash
curl http://localhost:8000/health
```

</details>

<details>
<summary><b>带鉴权问答</b></summary>

```bash
curl -H "X-API-Key: YOUR_LONG_RANDOM_KEY" \
  "http://localhost:8000/chat?company=acme&q=%E4%BD%A0%E4%BB%AC%E7%9A%84%E4%B8%BB%E8%90%A5%E4%B8%9A%E5%8A%A1%E6%98%AF%E4%BB%80%E4%B9%88%EF%BC%9F"
```

</details>

<details>
<summary><b>SSE 流式输出</b></summary>

```bash
curl -H "X-API-Key: YOUR_LONG_RANDOM_KEY" \
  -X POST "http://localhost:8000/chat?company=acme&q=%E4%BB%8B%E7%BB%8D%E4%B8%80%E4%B8%8B&stream=1"
```

</details>

---

## Sources 跳转（Text Fragments）

Sources 可能返回类似 deep link：

```text
https://example.com/page#:~:text=<snippet>
```

浏览器支持时会高亮命中片段并自动滚动到位置。

---

## 常见问题

- **提示“找不到索引”** → 先运行 `python tools/build_index.py <company>`。
- **Ollama 不可用/模型缺失** → 启动 Ollama 并执行 `ollama pull ...`。
- **鉴权失败** → 检查 `API_KEY` 与请求头 `X-API-Key`。
- **回答为空/无引用** → 确认导入与抽取成功，且索引已构建。

---

## License

待补充。
