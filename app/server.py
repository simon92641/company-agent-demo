import json
import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import List
from urllib.parse import quote

import requests
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Response
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from app.config import load_config
from app.lang import detect_lang, language_name, normalize_lang
from app.prompt import SYSTEM_PROMPT
from app.rag import get_base_url, retrieve

PROJECT_ROOT = Path(__file__).resolve().parents[1]
STATIC_DIR = PROJECT_ROOT / "static"
COMPANIES_DIR = PROJECT_ROOT / "companies"
WHITEPAPERS_DIR = STATIC_DIR / "whitepapers"
WHITEPAPER_INDEX = WHITEPAPERS_DIR / "index.json"

logger = logging.getLogger("whitepapers")
logging.basicConfig(level=logging.INFO)

WHITEPAPER_CACHE = {
    "mtime": None,
    "items": [],
}

app = FastAPI(title="Company Agent Demo")

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def require_api_key(x_api_key: str | None = Header(None, alias="X-API-Key")) -> None:
    config = load_config()
    api_key = str(config.get("API_KEY", "")).strip()
    provided = (x_api_key or "").strip()
    if api_key and provided != api_key:
        raise HTTPException(status_code=401, detail="未授权：缺少或无效的 X-API-Key")


def call_chat(model: str, messages: List[dict], base_url: str) -> str:
    if not model:
        raise HTTPException(status_code=500, detail="LLM_MODEL 未配置")

    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
    }

    try:
        response = requests.post(
            f"{base_url}/api/chat",
            json=payload,
            timeout=120,
        )
    except requests.RequestException as exc:
        raise HTTPException(status_code=500, detail=f"无法连接 Ollama: {exc}")

    if response.status_code != 200:
        raise HTTPException(
            status_code=500,
            detail=f"Ollama 接口错误 {response.status_code}: {response.text}",
        )

    try:
        data = response.json()
    except ValueError:
        raise HTTPException(status_code=500, detail="Ollama 返回的 JSON 无法解析")

    message = data.get("message", {})
    content = message.get("content", "").strip()
    if not content:
        raise HTTPException(status_code=500, detail="Ollama 返回内容为空")

    return content


def list_companies() -> list[dict]:
    if not COMPANIES_DIR.exists():
        return []

    companies: list[dict] = []
    for path in COMPANIES_DIR.iterdir():
        if not path.is_dir() or not (path / "sources.md").exists():
            continue
        entry = {"slug": path.name}
        meta_path = path / "sources_meta.json"
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                meta = {}
            if isinstance(meta, dict):
                name = str(meta.get("name", "")).strip()
                website = str(meta.get("website", "")).strip()
                if name:
                    entry["name"] = name
                if website:
                    entry["website"] = website
        entry["has_faq"] = (path / "faq.json").exists()
        companies.append(entry)
    return sorted(companies, key=lambda item: item.get("slug", ""))


def load_whitepapers() -> list[dict]:
    if not WHITEPAPER_INDEX.exists():
        return []

    try:
        mtime = WHITEPAPER_INDEX.stat().st_mtime
    except OSError:
        return []

    if WHITEPAPER_CACHE["mtime"] == mtime:
        return WHITEPAPER_CACHE["items"]

    try:
        raw = WHITEPAPER_INDEX.read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, ValueError):
        return []

    if not isinstance(data, list):
        return []

    items = []
    for item in data:
        if not isinstance(item, dict):
            continue
        items.append(
            {
                "id": str(item.get("id", "")).strip(),
                "title": str(item.get("title", "")).strip(),
                "summary": str(item.get("summary", "")).strip(),
                "file": str(item.get("file", "")).strip(),
                "published_at": str(item.get("published_at", "")).strip(),
                "tags": item.get("tags", []) if isinstance(item.get("tags", []), list) else [],
            }
        )

    WHITEPAPER_CACHE["mtime"] = mtime
    WHITEPAPER_CACHE["items"] = items
    return items


def get_whitepaper_by_id(whitepaper_id: str) -> dict | None:
    for item in load_whitepapers():
        if item.get("id") == whitepaper_id:
            return item
    return None


def parse_published_at(value: str) -> datetime:
    if not value:
        return datetime.min
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return datetime.min


def resolve_whitepaper_file(file_name: str) -> Path | None:
    if not file_name:
        return None
    base = WHITEPAPERS_DIR.resolve()
    candidate = (WHITEPAPERS_DIR / file_name).resolve()
    if base not in candidate.parents and candidate != base:
        return None
    if not candidate.exists() or not candidate.is_file():
        return None
    return candidate


def build_snippet(text: str, max_len: int = 110) -> str:
    clean = " ".join(text.split())
    return clean[:max_len]


def build_deep_link(url: str, snippet: str) -> str:
    if not url:
        return ""
    return f"{url}#:~:text={quote(snippet)}"


def format_sources(sources: List[dict]) -> List[dict]:
    formatted = []
    for item in sources:
        snippet = build_snippet(item.get("text", ""))
        url = item.get("url", "")
        formatted.append(
            {
                "chunk_id": item.get("chunk_id", ""),
                "score": item.get("score", 0.0),
                "title": item.get("title", ""),
                "url": url,
                "deep_link": build_deep_link(url, snippet),
                "snippet": snippet,
                "idx": item.get("idx", 0),
            }
        )
    return formatted


def build_system_prompt(lang_code: str) -> str:
    return (
        SYSTEM_PROMPT
        + f"\n\n[OUTPUT_LANGUAGE] {lang_code} - {language_name(lang_code)}\n"
        "You MUST respond only in this language."
    )


def build_user_prompt(context: str, question: str) -> str:
    return (
        "以下是与问题最相关的资料片段，请基于资料回答。\n\n"
        f"资料:\n{context}\n\n"
        f"问题: {question}\n\n"
        "请给出简洁、结构化的回答。"
    )


def resolve_language(lang: str | None, question: str) -> str:
    if lang is None or not lang.strip():
        return detect_lang(question)
    return normalize_lang(lang)


def build_context(sources: List[dict]) -> str:
    return "\n".join(f"[{item['idx']}] {item['text']}" for item in sources)


def chat_response(company: str, question: str, lang: str | None) -> dict:
    if not question.strip():
        raise HTTPException(status_code=400, detail="问题不能为空")

    config = load_config()
    top_k = int(config.get("TOP_K", 8))
    try:
        sources = retrieve(company, question, top_k=top_k, config=config)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    target_lang = resolve_language(lang, question)
    context = build_context(sources)
    answer = call_chat(
        str(config.get("LLM_MODEL", "")),
        [
            {"role": "system", "content": build_system_prompt(target_lang)},
            {"role": "user", "content": build_user_prompt(context, question)},
        ],
        get_base_url(config),
    )

    return {
        "answer": answer,
        "language": target_lang,
        "sources": format_sources(sources),
    }


def sse_event(event: str, payload: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


@app.get("/")
def index() -> FileResponse:
    index_path = STATIC_DIR / "index.html"
    if not index_path.exists():
        raise HTTPException(status_code=404, detail="找不到 static/index.html")
    return FileResponse(index_path)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/companies", dependencies=[Depends(require_api_key)])
def companies() -> list[dict]:
    return list_companies()


@app.get("/api/whitepapers")
def whitepapers() -> list[dict]:
    request_id = str(uuid.uuid4())
    items = load_whitepapers()
    logger.info("[whitepapers] request_id=%s count=%s", request_id, len(items))
    return items


@app.get("/whitepapers/{whitepaper_id}")
def whitepaper_file(whitepaper_id: str):
    request_id = str(uuid.uuid4())
    item = get_whitepaper_by_id(whitepaper_id)
    if not item:
        logger.info("[whitepapers] request_id=%s id=%s not_found", request_id, whitepaper_id)
        return JSONResponse(status_code=404, content={"detail": "白皮书不存在"})

    file_name = item.get("file", "")
    file_path = resolve_whitepaper_file(file_name)
    if not file_path:
        logger.info(
            "[whitepapers] request_id=%s id=%s file=%s missing",
            request_id,
            whitepaper_id,
            file_name,
        )
        return JSONResponse(status_code=404, content={"detail": "文件不存在"})

    cache_seconds = int(load_config().get("WHITEPAPER_CACHE_SECONDS", 3600))
    headers = {
        "Content-Disposition": f'inline; filename="{file_path.name}"',
        "Cache-Control": f"public, max-age={cache_seconds}",
    }
    logger.info(
        "[whitepapers] request_id=%s id=%s file=%s",
        request_id,
        whitepaper_id,
        file_path.name,
    )
    return FileResponse(file_path, media_type="application/pdf", headers=headers)


@app.get("/whitepaper/latest")
def whitepaper_latest():
    request_id = str(uuid.uuid4())
    items = load_whitepapers()
    if not items:
        logger.info("[whitepapers] request_id=%s latest_not_found", request_id)
        return JSONResponse(status_code=404, content={"detail": "暂无白皮书"})

    latest = max(items, key=lambda item: parse_published_at(item.get("published_at", "")))
    logger.info(
        "[whitepapers] request_id=%s latest_id=%s",
        request_id,
        latest.get("id", ""),
    )
    return RedirectResponse(url=f"/whitepapers/{latest.get('id', '')}")


@app.get("/whitepaper")
def whitepaper_page() -> HTMLResponse:
    html = """
<!doctype html>
<html lang="zh">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>白皮书预览</title>
    <style>
      body { font-family: "SF Pro Text", "Helvetica Neue", Arial, sans-serif; margin: 32px; color: #0b1f2a; }
      .card { border: 1px solid rgba(11,31,42,0.15); border-radius: 16px; padding: 20px; max-width: 900px; }
      .meta { color: #5b6770; font-size: 14px; }
      .actions { margin-top: 12px; }
      .btn { display: inline-block; padding: 10px 16px; border-radius: 999px; background: #81d8d0; color: #0f3f3b; text-decoration: none; font-weight: 600; }
      iframe { width: 100%; height: 75vh; border: none; margin-top: 20px; border-radius: 12px; }
    </style>
  </head>
  <body>
    <div class="card">
      <h2 id="title">最新白皮书</h2>
      <p id="summary" class="meta">加载中...</p>
      <div class="actions">
        <a id="openLink" class="btn" href="/whitepaper/latest" target="_blank" rel="noopener noreferrer">在线阅读</a>
      </div>
      <iframe id="previewFrame" title="Whitepaper Preview"></iframe>
    </div>
    <script>
      async function loadLatest() {
        try {
          const res = await fetch('/api/whitepapers');
          const items = await res.json();
          if (!items.length) {
            document.getElementById('summary').textContent = '暂无白皮书';
            return;
          }
          const latest = items.slice().sort((a, b) => (a.published_at || '').localeCompare(b.published_at || '')).pop();
          document.getElementById('title').textContent = latest.title || '最新白皮书';
          document.getElementById('summary').textContent = latest.summary || '';
          const link = `/whitepapers/${latest.id}`;
          document.getElementById('openLink').href = '/whitepaper/latest';
          document.getElementById('previewFrame').src = link;
        } catch (err) {
          document.getElementById('summary').textContent = '加载失败';
        }
      }
      loadLatest();
    </script>
  </body>
</html>
"""
    return HTMLResponse(content=html)


@app.get("/companies/{slug}/faq", dependencies=[Depends(require_api_key)])
def company_faq(slug: str) -> dict:
    faq_path = COMPANIES_DIR / slug / "faq.json"
    if not faq_path.exists():
        return {"slug": slug, "items": []}
    try:
        return json.loads(faq_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise HTTPException(status_code=500, detail="FAQ 文件损坏或无法读取")


@app.get("/chat", dependencies=[Depends(require_api_key)])
def chat_get(
    company: str = Query(..., description="公司名称，例如 acme"),
    q: str = Query(..., description="用户问题"),
    lang: str | None = Query(None, description="输出语言，例如 ja"),
) -> dict:
    return chat_response(company, q, lang)


@app.post("/chat", dependencies=[Depends(require_api_key)], response_model=None)
def chat_post(
    company: str = Query(..., description="公司名称，例如 acme"),
    q: str = Query(..., description="用户问题"),
    lang: str | None = Query(None, description="输出语言，例如 ja"),
    stream: int | None = Query(None, description="流式输出，1 表示开启"),
) -> Response:
    if stream:
        return chat_stream(company, q, lang)
    return chat_response(company, q, lang)


def chat_stream(company: str, question: str, lang: str | None) -> StreamingResponse:
    if not question.strip():
        raise HTTPException(status_code=400, detail="问题不能为空")

    config = load_config()
    top_k = int(config.get("TOP_K", 8))
    try:
        sources = retrieve(company, question, top_k=top_k, config=config)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    target_lang = resolve_language(lang, question)
    context = build_context(sources)
    payload = {
        "model": str(config.get("LLM_MODEL", "")),
        "messages": [
            {"role": "system", "content": build_system_prompt(target_lang)},
            {"role": "user", "content": build_user_prompt(context, question)},
        ],
        "stream": True,
    }

    base_url = get_base_url(config)
    if not payload["model"]:
        raise HTTPException(status_code=500, detail="LLM_MODEL 未配置")

    def event_stream():
        try:
            response = requests.post(
                f"{base_url}/api/chat",
                json=payload,
                timeout=120,
                stream=True,
            )
        except requests.RequestException as exc:
            yield sse_event("error", {"message": f"无法连接 Ollama: {exc}"})
            return

        if response.status_code != 200:
            yield sse_event(
                "error",
                {
                    "message": f"Ollama 接口错误 {response.status_code}: {response.text}"
                },
            )
            return

        try:
            for line in response.iter_lines(decode_unicode=True):
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except ValueError:
                    continue
                if data.get("error"):
                    yield sse_event("error", {"message": data.get("error")})
                    return
                message = data.get("message", {})
                content = message.get("content", "")
                if content:
                    yield sse_event("delta", {"text": content})
                if data.get("done"):
                    break
        except requests.RequestException as exc:
            yield sse_event("error", {"message": f"Ollama 流式中断: {exc}"})
            return

        yield sse_event(
            "sources",
            {
                "sources": format_sources(sources),
                "language": target_lang,
            },
        )
        yield sse_event("done", {})

    return StreamingResponse(event_stream(), media_type="text/event-stream")
