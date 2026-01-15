import json
import re
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import requests

from app.config import load_config

PROJECT_ROOT = Path(__file__).resolve().parents[1]
COMPANIES_DIR = PROJECT_ROOT / "companies"


def get_base_url(config: Dict | None = None) -> str:
    cfg = config or load_config()
    return str(cfg.get("OLLAMA_BASE_URL", "")).rstrip("/")


def get_embed_model(config: Dict | None = None) -> str:
    cfg = config or load_config()
    return str(cfg.get("EMBED_MODEL", ""))


def get_company_dir(company: str) -> Path:
    return COMPANIES_DIR / company


def read_sources(company: str) -> str:
    sources_path = get_company_dir(company) / "sources.md"
    if not sources_path.exists():
        raise FileNotFoundError(
            f"找不到资料文件: {sources_path}. 请检查 company 名称或创建 sources.md"
        )
    return sources_path.read_text(encoding="utf-8")


def load_sources_meta(company: str) -> Dict:
    meta_path = get_company_dir(company) / "sources_meta.json"
    if not meta_path.exists():
        return {}
    try:
        return json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _parse_page_id(heading: str) -> int | None:
    match = re.search(r"(页面|page)\s*(\d+)", heading, re.IGNORECASE)
    if not match:
        return None
    try:
        return int(match.group(2))
    except ValueError:
        return None


def split_sources_by_page(text: str) -> List[Tuple[int | None, str]]:
    sections: List[Tuple[int | None, str]] = []
    current_id: int | None = None
    buffer: List[str] = []

    for line in text.splitlines():
        if line.startswith("## "):
            page_id = _parse_page_id(line)
            if page_id is not None:
                if buffer:
                    sections.append((current_id, "\n".join(buffer).strip()))
                    buffer = []
                current_id = page_id
                continue
        buffer.append(line)

    if buffer:
        sections.append((current_id, "\n".join(buffer).strip()))

    if not sections:
        sections = [(None, text.strip())]

    return sections


def chunk_text(
    text: str, max_chars: int | None = None, overlap: int | None = None
) -> List[str]:
    """Split text into small chunks for embedding.

    Strategy:
    1) Split by blank lines into paragraphs
    2) Long paragraphs are split by character window with overlap
    """

    if max_chars is None or overlap is None:
        config = load_config()
        if max_chars is None:
            max_chars = int(config.get("CHUNK_SIZE", 200))
        if overlap is None:
            overlap = int(config.get("CHUNK_OVERLAP", 30))

    clean_text = text.replace("\r\n", "\n").strip()
    if not clean_text:
        return []

    paragraphs = [p.strip() for p in clean_text.split("\n\n") if p.strip()]
    chunks: List[str] = []

    for para in paragraphs:
        if len(para) <= max_chars:
            chunks.append(para)
            continue

        start = 0
        while start < len(para):
            end = min(start + max_chars, len(para))
            piece = para[start:end].strip()
            if piece:
                chunks.append(piece)
            if end >= len(para):
                break
            start = max(0, end - overlap)

    return chunks


def _post_json(url: str, payload: Dict, timeout: int = 60) -> Dict:
    try:
        response = requests.post(url, json=payload, timeout=timeout)
    except requests.RequestException as exc:
        raise RuntimeError(f"无法连接 Ollama: {exc}") from exc

    if response.status_code != 200:
        message = f"Ollama 接口错误 {response.status_code}: {response.text}"
        if "context length" in response.text:
            message += "。可尝试调小 config.json 或环境变量里的 CHUNK_SIZE"
        raise RuntimeError(message)

    try:
        return response.json()
    except ValueError as exc:
        raise RuntimeError("Ollama 返回的 JSON 无法解析") from exc


def embed_texts(texts: List[str], base_url: str, model: str) -> np.ndarray:
    if not texts:
        raise ValueError("没有可用于向量化的文本")

    embeddings: List[List[float]] = []
    for text in texts:
        data = _post_json(
            f"{base_url}/api/embeddings",
            {"model": model, "prompt": text},
            timeout=120,
        )
        if "embedding" not in data:
            raise RuntimeError("Ollama embeddings 返回缺少 embedding 字段")
        embeddings.append(data["embedding"])

    return np.array(embeddings, dtype=np.float32)


def save_index(
    company: str, chunks: List[Dict], vectors: np.ndarray, model: str
) -> None:
    company_dir = get_company_dir(company)
    rag_dir = company_dir / "rag"
    rag_dir.mkdir(parents=True, exist_ok=True)

    ids = [chunk["chunk_id"] for chunk in chunks]
    texts = [chunk["text"] for chunk in chunks]

    np.save(rag_dir / "vectors.npy", vectors)
    meta = {
        "company": company,
        "embed_model": model,
        "ids": ids,
        "texts": texts,
        "chunks": chunks,
    }
    (rag_dir / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_index(company: str) -> Dict:
    rag_dir = get_company_dir(company) / "rag"
    vectors_path = rag_dir / "vectors.npy"
    meta_path = rag_dir / "meta.json"

    if not vectors_path.exists() or not meta_path.exists():
        raise FileNotFoundError(
            f"找不到索引文件: {rag_dir}. 请先运行 python tools/build_index.py {company}"
        )

    vectors = np.load(vectors_path)
    meta = json.loads(meta_path.read_text(encoding="utf-8"))

    return {
        "vectors": vectors,
        "ids": meta.get("ids", []),
        "texts": meta.get("texts", []),
        "chunks": meta.get("chunks", []),
        "embed_model": meta.get("embed_model", ""),
    }


def cosine_similarity(matrix: np.ndarray, vector: np.ndarray) -> np.ndarray:
    """Compute cosine similarity between each row in matrix and vector."""
    if matrix.ndim != 2 or vector.ndim != 1:
        raise ValueError("向量维度不匹配")

    matrix_norm = np.linalg.norm(matrix, axis=1)
    vector_norm = np.linalg.norm(vector)

    if vector_norm == 0:
        return np.zeros(matrix.shape[0], dtype=np.float32)

    denom = matrix_norm * vector_norm
    denom = np.where(denom == 0, 1e-12, denom)

    return (matrix @ vector) / denom


def retrieve(
    company: str, query: str, top_k: int = 4, config: Dict | None = None
) -> List[Dict]:
    cfg = config or load_config()
    base_url = get_base_url(cfg)
    embed_model = get_embed_model(cfg)

    index = load_index(company)
    chunks = index.get("chunks") or []
    texts = [chunk.get("text", "") for chunk in chunks] if chunks else index["texts"]
    if not texts:
        raise RuntimeError("索引中没有可用文本")

    query_vec = embed_texts([query], base_url, embed_model)[0]
    scores = cosine_similarity(index["vectors"], query_vec)

    top_indices = np.argsort(scores)[::-1][:top_k]
    results = []
    for rank, idx in enumerate(top_indices, start=1):
        if chunks:
            chunk = chunks[idx]
            result = {
                "idx": rank,
                "chunk_id": chunk.get("chunk_id", index["ids"][idx]),
                "text": chunk.get("text", ""),
                "score": float(scores[idx]),
                "page_id": chunk.get("page_id", ""),
                "url": chunk.get("url", ""),
                "title": chunk.get("title", ""),
            }
        else:
            result = {
                "idx": rank,
                "chunk_id": index["ids"][idx],
                "text": index["texts"][idx],
                "score": float(scores[idx]),
                "page_id": "",
                "url": "",
                "title": "",
            }
        results.append(result)

    return results


def build_index(company: str, config: Dict | None = None) -> None:
    cfg = config or load_config()
    base_url = get_base_url(cfg)
    embed_model = get_embed_model(cfg)

    raw_text = read_sources(company)
    sources_meta = load_sources_meta(company)
    page_map = {
        int(page.get("id")): page
        for page in sources_meta.get("pages", [])
        if isinstance(page, dict) and page.get("id") is not None
    }

    sections = split_sources_by_page(raw_text)
    chunks: List[Dict] = []
    chunk_counter = 0
    for page_id, section_text in sections:
        if page_map and page_id is None:
            continue
        if not section_text:
            continue
        section_chunks = chunk_text(
            section_text,
            max_chars=int(cfg.get("CHUNK_SIZE", 200)),
            overlap=int(cfg.get("CHUNK_OVERLAP", 30)),
        )
        page_meta = page_map.get(page_id) if page_id is not None else None
        for chunk in section_chunks:
            chunk_counter += 1
            chunks.append(
                {
                    "chunk_id": f"{company}-{chunk_counter:04d}",
                    "text": chunk,
                    "page_id": f"{page_id:03d}" if page_id is not None else "",
                    "url": str(page_meta.get("url", "")).strip() if page_meta else "",
                    "title": str(page_meta.get("title", "")).strip() if page_meta else "",
                }
            )

    if not chunks:
        raise ValueError("sources.md 内容为空，无法建立索引")

    vectors = embed_texts([chunk["text"] for chunk in chunks], base_url, embed_model)
    save_index(company, chunks, vectors, embed_model)
