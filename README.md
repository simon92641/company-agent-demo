# Company Agent Demo (Ollama + FastAPI)

这是一个可产品化的 RAG Demo：
- 读取 `companies/<slug>/sources.md`
- 切块并调用 Ollama `/api/embeddings` 生成向量
- 支持多语言自动回复、引用编号、API Key 鉴权
- 支持 Sources 可跳转官网命中段落（Text Fragments）
- 提供网页 Demo、FAQ 缓存与公司导入流水线
- 自动发现 URL：robots.txt sitemap → 常见 sitemap → HTML sitemap → RSS → BFS 扩散
- 语言过滤：默认只抓英文 + 简体中文（其它语言版本页面直接跳过）
- JS 兜底抓取：requests 内容过短/站点偏 SPA 时自动用 Playwright 渲染抓取（可选全站 JS 模式）

## 目录结构
```
company-agent-demo/
  app/
    __init__.py
    config.py
    lang.py
    prompt.py
    rag.py
    server.py
  tools/
    build_index.py
  scripts/
    ingest_company.py
    reindex_all.py
  companies/
    <slug>/
      sources.md     建索引用的（每个页面的文本，url来源）
      sources_meta.json   记录抓的url，存的对应文件，时间--做增量更新
      faq.json      快速问答
  static/
    index.html
  config.json
  requirements.txt
  README.md
  .gitignore
```

## 配置说明
- 默认配置在 `app/config.py`
- 根目录 `config.json` 会覆盖默认值
- 环境变量优先级最高（env > config.json > defaults）

示例 `config.json`（已提供，可直接修改）：
```json
{
  "OLLAMA_BASE_URL": "http://localhost:11434",
  "LLM_MODEL": "qwen3:8b",
  "EMBED_MODEL": "bge-m3:latest",
  "API_KEY": "change-me-to-a-long-random-string"
}
```

说明：
- `API_KEY` 为空时不启用鉴权；非空则要求请求头 `X-API-Key`。

## 从零开始运行
以下命令在 macOS 上测试通过：

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
ollama pull qwen3:8b && ollama pull bge-m3:latest
python tools/build_index.py acme
uvicorn app.server:app --reload --port 8000
```

## 网页 Demo
启动服务后访问：
```
http://localhost:8000/
```
页面顶部可以输入 API Key。

### 网页使用说明（1 分钟上手）
1. 在“API Key”输入框输入：simon
2. 点击「重新加载」：刷新公司列表与 Quick Questions（导入新公司后必须点一次）
3. 在「公司」下拉框选择要查询的公司
4. 两种问答方式：
   - 快速问题（Quick Questions）：预先缓存好的常见问题，点击即可立即出答案（不用等）
   - 实时问答：在输入框输入你的问题，按 Enter 或点击发送，等待模型响应（会检索公司网页资料并给出引用 Sources）

小提示：
- 若某公司没有 Quick Questions，说明 faq.json 未生成，仍可使用实时问答。
- 答案中的 Sources 可点击跳转到官网对应段落。

## curl 测试
```bash
curl http://localhost:8000/health
```

带鉴权访问：
```bash
curl -H "X-API-Key: change-me-to-a-long-random-string" \
  "http://localhost:8000/chat?company=acme&q=你们的主营业务是什么？"
```

## 流式输出（SSE）
使用 POST 并带 `stream=1`：
```bash
curl -H "X-API-Key: change-me-to-a-long-random-string" \
  -X POST "http://localhost:8000/chat?company=acme&q=介绍一下&stream=1"
```

## Sources 跳转说明（Text Fragments）
Sources 返回 `deep_link`，链接形式为：
```
https://example.com/page#:~:text=<snippet>
```
浏览器支持时会高亮命中片段并滚动到位置。

## 公司导入流水线（Onboarding Pipeline）
一键导入公开网页并生成索引与 FAQ：

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
- `--seed` 可多次传入，用于指定多个入口页面
- 默认仅抓取同域名页面，抓取间隔默认 1 秒
- 抽取正文使用 trafilatura，仅用于公开网页内容

## 批量重建索引
```bash
python scripts/reindex_all.py
```

## FAQ 缓存
- FAQ 保存在 `companies/<slug>/faq.json`
- 网页 Demo 会优先展示 Quick Questions
- 若 FAQ 不存在会回退到实时问答

## 常见问题
- 如果报错“找不到索引”，请先运行：`python tools/build_index.py <company>`
- 如果 Ollama 不可用，请先启动 Ollama 并确保模型已 `pull`
- 抓取遵守频率限制，仅用于公开网页与测试用途

<div align="center">

# Company Agent Demo (Ollama + FastAPI)

**可产品化的 RAG 公司知识库 Demo｜多语言｜引用溯源｜API Key 鉴权｜网页 UI**

<!-- Badges: 你可以按需删减/替换 -->
![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-ready-009688)
![RAG](https://img.shields.io/badge/RAG-embeddings%20%2B%20citations-orange)
![License](https://img.shields.io/badge/license-MIT-informational)

</div>

> 这个项目演示了一个“按公司导入公开网页 → 建索引 → 对话问答”的 RAG 流水线：
> - 读取 `companies/<slug>/sources.md`
> - 切块并调用 Ollama `/api/embeddings` 生成向量
> - 多语言自动回复、引用编号（带 deep link）、API Key 鉴权
> - 网页 Demo（含 Quick Questions/FAQ 缓存）与公司导入脚本

---

## 目录

- [效果预览](#效果预览)
- [功能亮点](#功能亮点)
- [目录结构](#目录结构)
- [从零开始运行](#从零开始运行)
- [配置说明](#配置说明)
- [接口调用示例](#接口调用示例)
- [Sources 跳转说明（Text Fragments）](#sources-跳转说明text-fragments)
- [公司导入流水线（Onboarding Pipeline）](#公司导入流水线onboarding-pipeline)
- [批量重建索引](#批量重建索引)
- [FAQ 缓存](#faq-缓存)
- [常见问题](#常见问题)
- [Roadmap](#roadmap)

---

## 效果预览

> 建议你放 1 张截图 + 1 个动图（可选）。
>
> - 截图：`assets/screenshot.png`
> - 动图：`assets/demo.gif`
>
> 然后把下面两行的路径替换成你自己的文件。

![Web Demo Screenshot](assets/screenshot.png)

<!-- 可选：如果你有录屏动图，取消注释 -->
<!-- ![Demo GIF](assets/demo.gif) -->

---

## 功能亮点

- ✅ **可产品化的 RAG 结构**：公司维度的知识库（`companies/<slug>/...`）
- ✅ **多语言自动回复**：根据用户问题自动选择语言
- ✅ **带编号引用 + 深链跳转**：Sources 返回 `deep_link`，可定位到命中文本
- ✅ **API Key 鉴权**：通过请求头 `X-API-Key` 控制访问
- ✅ **网页 Demo**：开箱即用的静态页面 UI
- ✅ **FAQ 缓存**：优先展示 Quick Questions，不存在则回退实时问答

---

## 目录结构

```
company-agent-demo/
  app/
    __init__.py
    config.py
    lang.py
    prompt.py
    rag.py
    server.py
  tools/
    build_index.py
  scripts/
    ingest_company.py
    reindex_all.py
  companies/
    <slug>/
      sources.md          建索引用（每个页面文本 + url 来源）
      sources_meta.json   记录抓取 url、对应文件、时间（用于增量更新）
      faq.json            快速问答缓存
  static/
    index.html
  config.json
  requirements.txt
  README.md
  .gitignore
```

---

## 从零开始运行

以下命令在 macOS 上测试通过：

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 拉取模型（按需更换）
ollama pull qwen3:8b
ollama pull bge-m3:latest

# 为公司构建索引（示例：acme）
python tools/build_index.py acme

# 启动服务
uvicorn app.server:app --reload --port 8000
```

启动后访问网页 Demo：

```text
http://localhost:8000/
```

---

## 配置说明

- 默认配置在 `app/config.py`
- 根目录 `config.json` 会覆盖默认值
- 环境变量优先级最高（env > config.json > defaults）

示例 `config.json`（已提供，可直接修改）：

```json
{
  "OLLAMA_BASE_URL": "http://localhost:11434",
  "LLM_MODEL": "qwen3:8b",
  "EMBED_MODEL": "bge-m3:latest",
  "API_KEY": "change-me-to-a-long-random-string"
}
```

说明：
- `API_KEY` 为空时不启用鉴权；非空则要求请求头 `X-API-Key`。

---

## 接口调用示例

健康检查：

```bash
curl http://localhost:8000/health
```

带鉴权访问：

```bash
curl -H "X-API-Key: change-me-to-a-long-random-string" \
  "http://localhost:8000/chat?company=acme&q=你们的主营业务是什么？"
```

流式输出（SSE）：

```bash
curl -H "X-API-Key: change-me-to-a-long-random-string" \
  -X POST "http://localhost:8000/chat?company=acme&q=介绍一下&stream=1"
```

---

## Sources 跳转说明（Text Fragments）

Sources 会返回 `deep_link`，链接形式为：

```text
https://example.com/page#:~:text=<snippet>
```

浏览器支持时会高亮命中片段并滚动到位置。

---

## 公司导入流水线（Onboarding Pipeline）

一键导入公开网页并生成索引与 FAQ：

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
- `--seed` 可多次传入，用于指定多个入口页面
- 默认仅抓取同域名页面，抓取间隔默认 1 秒
- 抽取正文使用 trafilatura，仅用于公开网页内容

---

## 批量重建索引

```bash
python scripts/reindex_all.py
```

---

## FAQ 缓存

- FAQ 保存在 `companies/<slug>/faq.json`
- 网页 Demo 会优先展示 Quick Questions
- 若 FAQ 不存在会回退到实时问答

---

## 常见问题

- 如果报错“找不到索引”，请先运行：`python tools/build_index.py <company>`
- 如果 Ollama 不可用，请先启动 Ollama 并确保模型已 `pull`
- 抓取遵守频率限制，仅用于公开网页与测试用途

---

## Roadmap

- [ ] 添加 Docker / docker-compose 一键启动
- [ ] 增加更漂亮的前端（搜索/引用展开/多公司切换）
- [ ] 增量更新与定时抓取（按 `sources_meta.json`）
- [ ] 更完善的评测与日志（trace / latency / token usage）

```
## 迭代记录

> 约定：每次对抓取/索引/FAQ/引用链路做调整，都在这里追加一条，方便回溯。

### 2026-01-06
- 抓取稳定性：为 requests 增加 `Accept-Language: zh-CN,zh;q=0.9,en;q=0.8`，减少站点按 Geo/IP 跳转到其它语言版本。
- 编码修复：统一用 `resp.apparent_encoding` 纠正常见的 `ISO-8859-1` 误判，减少 Sources 乱码（mojibake）。
- 邮箱提取：支持 Cloudflare Email Protection（`/cdn-cgi/l/email-protection` / `data-cfemail`）解码替换，避免出现 `[email protected]`。
- 语言兜底：若正文含日文假名/韩文 Hangul，则不入库，避免污染索引与引用。
