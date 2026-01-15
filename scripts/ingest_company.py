import argparse
import gzip
import heapq
import json
import re
import sys
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional
from urllib.parse import (
    parse_qsl,
    quote,
    urlencode,
    urljoin,
    urlparse,
)

import requests
from bs4 import BeautifulSoup
from trafilatura import extract

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
COMPANIES_DIR = PROJECT_ROOT / "companies"

USER_AGENT = "CompanyAgentDemo/1.0"

# 信息密度优先：尽量过滤掉明显低价值/非HTML资源
EXCLUDE_EXTENSIONS = {
    ".pdf",
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".webp",
    ".svg",
    ".ico",
    ".css",
    ".js",
    ".map",
    ".json",
    ".xml",
    ".zip",
    ".rar",
    ".7z",
    ".gz",
    ".mp4",
    ".mp3",
    ".mov",
    ".avi",
    ".woff",
    ".woff2",
    ".ttf",
    ".eot",
}

EXCLUDE_PATH_SUBSTRINGS = {
    "/wp-admin",
    "/wp-login",
    "/login",
    "/signin",
    "/signup",
    "/logout",
    "/account",
    "/cart",
    "/checkout",
    "/privacy",
    "/terms",
    "/cookie",
    "/legal",
    "/policies",
    "/search",
    "/tag/",
    "/category/",
    "/author/",
    "/cdn-cgi/",
}

TRACKING_QUERY_KEYS = {
    "gclid",
    "fbclid",
    "msclkid",
    "igshid",
    "mc_cid",
    "mc_eid",
    "mkt_tok",
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "_hsenc",
    "_hsmi",
    "hsctatracking",
    "ref",
    "ref_src",
    "source",
}


TRACKING_QUERY_PREFIXES = ("utm_",)

# 语言过滤：默认只保留英文 + 简体中文（其它语言版本页面直接跳过）
DEFAULT_KEEP_LANGS = "en,zh-cn"

# 归一化映射：en-* -> en；zh/zh-hans -> zh-cn
LANG_ALIASES = {
    # English
    "en-us": "en",
    "en-gb": "en",
    "en-au": "en",
    "en-ca": "en",
    "en-sg": "en",
    # Simplified Chinese
    "zh": "zh-cn",
    "zh-cn": "zh-cn",
    "zh-hans": "zh-cn",
}

# 语言检测白名单：避免把国家/地区代码当成语言（例如 /us/、/uk/）
# 这里只用于“检测/过滤”，不是用于最终保留语言。
KNOWN_LANG_CODES = {
    # English
    "en",
    "en-us",
    "en-gb",
    "en-au",
    "en-ca",
    "en-sg",
    # Chinese
    "zh",
    "zh-cn",
    "zh-hans",
    "zh-hant",
    "zh-tw",
    "zh-hk",
    # Common languages
    "ja",
    "ko",
    "fr",
    "de",
    "es",
    "it",
    "pt",
    "pt-br",
    "ru",
    "nl",
    "sv",
    "no",
    "da",
    "fi",
    "pl",
    "tr",
    "ar",
    "he",
    "id",
    "th",
    "vi",
}

# 常见地区前缀（非语言）：用于 bucket/priority 识别时剥离，如 /us/products...
COMMON_REGION_PREFIXES = {
    "us",
    "uk",
    "au",
    "ca",
    "sg",
    "in",
    "de",
    "fr",
    "jp",
    "kr",
    "cn",
    "tw",
    "hk",
}

def canonical_lang(code: str) -> str:
    c = (code or "").strip().lower().replace("_", "-")
    return LANG_ALIASES.get(c, c)

def parse_keep_langs(s: str) -> set[str]:
    parts = re.split(r"[,\s]+", (s or "").strip())
    out = {canonical_lang(p) for p in parts if p}
    # 兜底：至少保留英文
    return out or {"en"}

def extract_lang_from_url(url: str) -> str:
    """Try to detect a language code from subdomain or first path segment.

    Examples:
      - fr.example.com/... -> fr
      - example.com/fr/... -> fr
      - example.com/zh-cn/... -> zh-cn
    """
    p = urlparse(url)

    host = (p.netloc or "").lower()
    labels = [x for x in host.split(".") if x]

    def _is_lang_token(tok: str) -> bool:
        t = (tok or "").strip().lower().replace("_", "-")
        if not t:
            return False
        # only accept known language codes to avoid /us/, /uk/ etc.
        if t in KNOWN_LANG_CODES:
            return True
        # allow variants like en-us, pt-br only if the base is known
        if re.fullmatch(r"[a-z]{2}(-[a-z]{2,4})?", t):
            base = t.split("-", 1)[0]
            return base in {"en", "zh", "fr", "de", "es", "it", "pt", "ru", "ja", "ko", "nl", "sv", "no", "da", "fi", "pl", "tr", "ar", "he", "id", "th", "vi"}
        return False

    # language subdomain: fr.example.com / zh-cn.example.com
    if len(labels) >= 3:
        first = labels[0]
        if first != "www" and _is_lang_token(first):
            return canonical_lang(first)

    # first path segment: /fr/... /zh-cn/... (NOTE: exclude region prefixes like /us/)
    path = (p.path or "").strip("/")
    if path:
        first_seg = path.split("/", 1)[0].lower()
        if first_seg in COMMON_REGION_PREFIXES:
            return ""
        if _is_lang_token(first_seg):
            return canonical_lang(first_seg)

    return ""


def normalize_url(raw_url: str) -> str:
    url = (raw_url or "").strip()
    if not url:
        return ""
    if url.startswith("//"):
        url = "https:" + url

    parsed = urlparse(url)
    if not parsed.scheme:
        url = "https://" + url
        parsed = urlparse(url)

    # drop fragment, normalize netloc, strip tracking query params
    netloc = (parsed.netloc or "").lower()
    query = strip_tracking_query(parsed.query)
    parsed = parsed._replace(fragment="", netloc=netloc, query=query)

    return parsed.geturl()


def strip_tracking_query(query: str) -> str:
    if not query:
        return ""
    pairs = parse_qsl(query, keep_blank_values=False)
    kept = []
    for k, v in pairs:
        kl = (k or "").lower()
        if kl in TRACKING_QUERY_KEYS:
            continue
        if any(kl.startswith(p) for p in TRACKING_QUERY_PREFIXES):
            continue
        kept.append((k, v))
    return urlencode(kept, doseq=True)


def is_same_domain(url: str, allowed_netloc: str) -> bool:
    if not allowed_netloc:
        return True
    netloc = urlparse(url).netloc.lower()
    allowed = allowed_netloc.lower()
    if netloc == allowed:
        return True
    return netloc.endswith("." + allowed)




def get_skip_reason(url: str, allowed_langs: set[str]) -> str:
    """Return a non-empty reason string if the URL should be skipped."""
    try:
        p = urlparse(url)
    except Exception:
        return "bad_url"

    if p.scheme not in ("http", "https"):
        return "bad_scheme"

    # language filter: if url explicitly indicates a language and it's not allowed -> skip
    lang = extract_lang_from_url(url)
    if lang and lang not in allowed_langs:
        return f"lang_not_allowed:{lang}"

    path = (p.path or "").lower()

    # file extension filter
    for ext in EXCLUDE_EXTENSIONS:
        if path.endswith(ext):
            return f"excluded_ext:{ext}"

    # obvious low-value paths
    for sub in EXCLUDE_PATH_SUBSTRINGS:
        if sub in path:
            return f"excluded_path:{sub}"

    return ""


def should_skip_url(url: str, allowed_langs: set[str]) -> bool:
    return bool(get_skip_reason(url, allowed_langs))


def extract_links(html: str, base_url: str) -> Iterable[str]:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup.find_all("a", href=True):
        href = (tag.get("href", "") or "").strip()
        if not href:
            continue
        if href.startswith("#"):
            continue
        if href.startswith("mailto:") or href.startswith("tel:"):
            continue
        if href.startswith("javascript:"):
            continue
        full_url = normalize_url(urljoin(base_url, href))
        if full_url:
            yield full_url


def extract_title(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    title = soup.title.string if soup.title else ""
    return (title or "").strip()


def save_text(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def build_sources_md(
    company_dir: Path,
    name: str,
    website: str,
    fetched_at: str,
    pages: list[dict],
) -> None:
    lines = [f"# {name}", "", f"官网：{website}", f"导入时间：{fetched_at}", ""]

    extracted_pages = [p for p in pages if p.get("text")]
    if not extracted_pages:
        lines.append("暂无可用正文内容。")
        lines.append("")
    else:
        for page in extracted_pages:
            page_id = page["id"]
            text = page["text"].strip()
            url = page["url"]
            title = (page.get("title") or "").strip()
            rendered = bool(page.get("rendered", False))

            lines.append(f"## 页面 {page_id}")
            if title:
                lines.append(f"标题：{title}")
                lines.append("")
            if rendered:
                lines.append("（JS 渲染抓取）")
                lines.append("")

            lines.append(text)
            lines.append("")
            lines.append("来源：")
            lines.append(f"- {url}")
            lines.append("")

    sources_path = company_dir / "sources.md"
    save_text(sources_path, "\n".join(lines).strip() + "\n")


def build_snippet(text: str, max_len: int = 100) -> str:
    clean = " ".join(text.split())
    return clean[:max_len]


def build_deep_link(url: str, snippet: str) -> str:
    if not url:
        return ""
    return f"{url}#:~:text={quote(snippet)}"


def _requests_get(url: str, timeout: int = 30) -> Optional[requests.Response]:
    try:
        return requests.get(
            url,
            headers={
                "User-Agent": USER_AGENT,
                # 尽量避免站点按 Geo/IP 默认跳到日/韩/欧语版本
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            },
            timeout=timeout,
            allow_redirects=True,
        )
    except requests.RequestException:
        return None


def _response_text(resp: Optional[requests.Response]) -> str:
    """Return decoded response text with a safer encoding guess.

    Many sites omit charset; requests may default to ISO-8859-1 and produce mojibake.
    """
    if resp is None:
        return ""
    try:
        if (not resp.encoding) or (resp.encoding.lower() == "iso-8859-1"):
            resp.encoding = resp.apparent_encoding or "utf-8"
        return resp.text or ""
    except Exception:
        try:
            return (resp.content or b"").decode("utf-8", errors="replace")
        except Exception:
            return ""


def decode_cfemail(cfhex: str) -> str:
    """Decode Cloudflare email protection hex string to a real email."""
    try:
        data = bytes.fromhex(cfhex)
        key = data[0]
        decoded = bytes(b ^ key for b in data[1:])
        return decoded.decode("utf-8", errors="ignore")
    except Exception:
        return ""


def replace_cloudflare_emails(html: str) -> str:
    """Replace Cloudflare email-protection placeholders like [email&#160;protected]."""
    if not html or "email-protection" not in html:
        return html

    soup = BeautifulSoup(html, "lxml")

    # 1) <a class="__cf_email__" data-cfemail="...">[email&#160;protected]</a>
    for a in soup.select("a.__cf_email__"):
        cf = a.get("data-cfemail") or ""
        email = decode_cfemail(cf)
        if email:
            a.string = email
            a["href"] = f"mailto:{email}"

    # 2) href="/cdn-cgi/l/email-protection#...."
    for a in soup.find_all("a", href=True):
        href = a.get("href", "") or ""
        m = re.search(r"/cdn-cgi/l/email-protection#([0-9a-fA-F]+)", href)
        if m:
            email = decode_cfemail(m.group(1))
            if email:
                a.string = email
                a["href"] = f"mailto:{email}"

    return str(soup)


def _get_root_url(website: str) -> str:
    w = normalize_url(website)
    p = urlparse(w)
    if not p.scheme or not p.netloc:
        return w
    return f"{p.scheme}://{p.netloc}"


def discover_sitemaps_from_robots(root_url: str) -> list[str]:
    robots_url = normalize_url(root_url.rstrip("/") + "/robots.txt")
    resp = _requests_get(robots_url, timeout=20)
    if not resp or resp.status_code != 200:
        return []

    sitemaps: list[str] = []
    for line in (_response_text(resp) or "").splitlines():
        line = line.strip()
        if not line:
            continue
        # Sitemap: <url>
        if line.lower().startswith("sitemap:"):
            sm = line.split(":", 1)[1].strip()
            sm = normalize_url(sm)
            if sm:
                sitemaps.append(sm)

    # 去重但保留顺序
    seen: set[str] = set()
    out: list[str] = []
    for u in sitemaps:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def _decompress_if_needed(url: str, resp: requests.Response) -> bytes:
    content = resp.content or b""
    if url.lower().endswith(".gz"):
        try:
            return gzip.decompress(content)
        except Exception:
            return content

    ct = (resp.headers.get("content-type") or "").lower()
    if "gzip" in ct:
        try:
            return gzip.decompress(content)
        except Exception:
            return content

    return content


def parse_sitemap_bytes(xml_bytes: bytes) -> tuple[list[str], list[str]]:
    """Return (child_sitemaps, urls)."""
    try:
        soup = BeautifulSoup(xml_bytes, "xml")
    except Exception:
        return ([], [])

    if soup.find("sitemapindex") is not None:
        locs = [normalize_url(loc.get_text(strip=True)) for loc in soup.find_all("loc")]
        locs = [u for u in locs if u]
        return (locs, [])

    if soup.find("urlset") is not None:
        locs = [normalize_url(loc.get_text(strip=True)) for loc in soup.find_all("loc")]
        locs = [u for u in locs if u]
        return ([], locs)

    # fallback: try any <loc>
    locs = [normalize_url(loc.get_text(strip=True)) for loc in soup.find_all("loc")]
    locs = [u for u in locs if u]
    return ([], locs)



def discover_urls_from_sitemaps(
    sitemap_urls: list[str],
    allowed_domain: str,
    same_domain_only: bool,
    limit: int,
    allowed_langs: set[str],
) -> list[str]:
    """Recursively parse sitemap index/urlset and return discovered page URLs."""
    discovered: list[str] = []
    seen_sitemaps: set[str] = set()
    seen_urls: set[str] = set()

    q = deque(sitemap_urls)
    while q and len(discovered) < max(limit, 0):
        sm = q.popleft()
        if not sm or sm in seen_sitemaps:
            continue
        seen_sitemaps.add(sm)

        resp = _requests_get(sm, timeout=40)
        if not resp or resp.status_code != 200:
            continue

        xml_bytes = _decompress_if_needed(sm, resp)
        child_sitemaps, urls = parse_sitemap_bytes(xml_bytes)

        for child in child_sitemaps:
            if child and child not in seen_sitemaps:
                q.append(child)

        for u in urls:
            if not u:
                continue
            if same_domain_only and not is_same_domain(u, allowed_domain):
                continue
            if should_skip_url(u, allowed_langs):
                continue
            if u in seen_urls:
                continue
            seen_urls.add(u)
            discovered.append(u)
            if len(discovered) >= limit:
                break

    return discovered


def discover_html_sitemap_urls(root_url: str) -> list[str]:
    candidates = [
        root_url.rstrip("/") + "/sitemap",
        root_url.rstrip("/") + "/site-map",
        root_url.rstrip("/") + "/site_map",
        root_url.rstrip("/") + "/sitemap.html",
    ]

    out: list[str] = []
    for c in candidates:
        u = normalize_url(c)
        resp = _requests_get(u, timeout=25)
        if not resp or resp.status_code != 200:
            continue
        ct = (resp.headers.get("content-type") or "").lower()
        if "text/html" not in ct and "application/xhtml+xml" not in ct:
            # 也可能没带 header，继续尝试
            pass
        html = _response_text(resp) or ""
        if not html.strip():
            continue
        # 如果页面看起来像 XML sitemap，就不在这里处理
        if "<urlset" in html or "<sitemapindex" in html:
            continue
        for link in extract_links(html, u):
            out.append(link)

        # 命中一个就够（通常页面 sitemap 很大）
        if out:
            break

    # 去重保序
    seen: set[str] = set()
    dedup: list[str] = []
    for x in out:
        if x not in seen:
            seen.add(x)
            dedup.append(x)
    return dedup


def discover_feed_urls(root_url: str) -> list[str]:
    candidates = [
        root_url.rstrip("/") + "/feed",
        root_url.rstrip("/") + "/rss.xml",
        root_url.rstrip("/") + "/atom.xml",
        root_url.rstrip("/") + "/blog/rss.xml",
        root_url.rstrip("/") + "/news/rss.xml",
    ]

    out: list[str] = []
    for c in candidates:
        u = normalize_url(c)
        resp = _requests_get(u, timeout=25)
        if not resp or resp.status_code != 200:
            continue
        data = resp.content or b""
        # feed 通常是 xml
        try:
            soup = BeautifulSoup(data, "xml")
        except Exception:
            continue

        # RSS <item><link> or Atom <entry><link href="...">
        for tag in soup.find_all("link"):
            href = tag.get("href")
            if href:
                out.append(normalize_url(href))
            else:
                txt = tag.get_text(strip=True)
                if txt:
                    out.append(normalize_url(txt))

        if out:
            break

    # 去重保序
    seen: set[str] = set()
    dedup: list[str] = []
    for x in out:
        if x and x not in seen:
            seen.add(x)
            dedup.append(x)
    return dedup


def looks_js_heavy(html: str) -> bool:
    if not html:
        return True
    h = html.lower()
    # 常见的 SPA/SSR 痕迹
    if "id=\"__next\"" in h or "__next_data__" in h:
        return True
    if "window.__nuxt__" in h or "id=\"__nuxt\"" in h:
        return True
    if "data-reactroot" in h:
        return True
    if "enable javascript" in h or "requires javascript" in h:
        return True
    if "<noscript" in h and len(h) < 20000:
        return True
    # 超短且脚本很多
    if len(h) < 8000 and h.count("<script") >= 3:
        return True
    return False



def discover_initial_queue(
    website: str,
    seeds: list[str],
    max_pages: int,
    same_domain_only: bool,
    allowed_langs: set[str],
) -> list[str]:
    """优先级：robots.txt sitemap -> 常见 sitemap -> HTML sitemap -> feed -> seeds"""
    root_url = _get_root_url(website)
    base_domain = urlparse(normalize_url(website)).netloc

    sitemap_urls = discover_sitemaps_from_robots(root_url)

    # robots 没给就猜常见路径
    if not sitemap_urls:
        common = [
            root_url.rstrip("/") + "/sitemap.xml",
            root_url.rstrip("/") + "/sitemap_index.xml",
            root_url.rstrip("/") + "/sitemap-index.xml",
            root_url.rstrip("/") + "/sitemap.xml.gz",
            root_url.rstrip("/") + "/sitemap/sitemap.xml",
            root_url.rstrip("/") + "/sitemaps/sitemap.xml",
        ]
        for c in common:
            u = normalize_url(c)
            resp = _requests_get(u, timeout=25)
            if not resp or resp.status_code != 200:
                continue
            # 简单判断一下像 sitemap
            txt = (_response_text(resp) or "").lower()
            if "<urlset" in txt or "<sitemapindex" in txt or u.lower().endswith(".gz"):
                sitemap_urls.append(u)
                break

    discovered_urls: list[str] = []
    if sitemap_urls:
        discovered_urls = discover_urls_from_sitemaps(
            sitemap_urls=sitemap_urls,
            allowed_domain=base_domain,
            same_domain_only=same_domain_only,
            limit=min(max_pages * 10, 5000),
            allowed_langs=allowed_langs,
        )

    # HTML sitemap
    if not discovered_urls:
        html_sm = discover_html_sitemap_urls(root_url)
        discovered_urls.extend(html_sm)

    # feed
    if not discovered_urls:
        feed_urls = discover_feed_urls(root_url)
        discovered_urls.extend(feed_urls)

    # 合并：发现的 URL 优先，其次 seeds
    merged: list[str] = []
    seen: set[str] = set()

    for u in discovered_urls:
        if not u:
            continue
        if same_domain_only and not is_same_domain(u, base_domain):
            continue
        if should_skip_url(u, allowed_langs):
            continue
        if u in seen:
            continue
        seen.add(u)
        merged.append(u)

    for s in seeds:
        u = normalize_url(s)
        if not u:
            continue
        if same_domain_only and not is_same_domain(u, base_domain):
            continue
        if should_skip_url(u, allowed_langs):
            continue
        if u in seen:
            continue
        seen.add(u)
        merged.append(u)

    return merged



# --- Bucket/priority helpers for stable crawl ---

def _strip_region_prefix(path: str) -> str:
    p = (path or "").strip()
    if not p.startswith("/"):
        p = "/" + p
    segs = [s for s in p.split("/") if s]
    if segs and segs[0].lower() in COMMON_REGION_PREFIXES:
        segs = segs[1:]
    return "/" + "/".join(segs)


def bucket_url(url: str) -> str:
    """Coarse bucket for crawl budgeting."""
    try:
        p = urlparse(url)
    except Exception:
        return "other"
    path = _strip_region_prefix((p.path or "").lower())

    if path.startswith("/blog") or "/blog/" in path:
        return "blog"
    if path.startswith("/resources") or "/resources/" in path or path.startswith("/resource"):
        return "resources"
    if path.startswith("/news") or "/news/" in path:
        return "news"
    if path.startswith("/press") or "/press/" in path:
        return "press"
    if path.startswith("/events") or "/events/" in path or path.startswith("/event"):
        return "events"
    if path.startswith("/customers") or "/customers/" in path or path.startswith("/customer"):
        return "customers"
    if path.startswith("/case") or "/case/" in path or path.startswith("/stories") or "/stories/" in path:
        return "cases"

    return "other"


def default_bucket_caps(max_pages: int) -> dict[str, int]:
    """Stable defaults: prevent blog/resources from swallowing the whole budget."""
    mp = max(1, int(max_pages))
    return {
        "blog": max(20, int(mp * 0.15)),
        "resources": max(20, int(mp * 0.15)),
        "news": max(10, int(mp * 0.08)),
        "press": max(10, int(mp * 0.08)),
        "events": max(10, int(mp * 0.08)),
        # customers/cases are often useful but can be huge
        "customers": max(20, int(mp * 0.20)),
        "cases": max(20, int(mp * 0.20)),
        # other = uncapped (fill remaining)
        "other": mp,
    }


def score_url(url: str) -> int:
    """Priority score for crawling: higher = crawl earlier."""
    try:
        p = urlparse(url)
    except Exception:
        return -999

    path = _strip_region_prefix((p.path or "").lower())

    high = (
        "/products",
        "/product",
        "/platform",
        "/pricing",
        "/about",
        "/company",
        "/solutions",
        "/solution",
        "/customers",
        "/customer",
        "/contact",
        "/security",
        "/trust",
        "/compliance",
        "/docs",
        "/documentation",
    )

    low = (
        "/blog",
        "/news",
        "/press",
        "/events",
        "/resources",
        "/resource",
        "/tag/",
        "/category/",
        "/author/",
    )

    s = 0
    if any(h in path for h in high):
        s += 80
    if any(l in path for l in low):
        s -= 60

    # Prefer shorter, cleaner URLs
    if p.query:
        s -= 12
    depth = len([x for x in path.split("/") if x])
    s -= max(0, depth - 4) * 2

    return s


def crawl_site(
    slug: str,
    name: str,
    website: str,
    seeds: list[str],
    max_pages: int,
    same_domain_only: bool,
    sleep_seconds: float,
    min_chars: int,
    js_fallback: bool,
    js_only: bool,
    js_wait_until: str,
    js_timeout_ms: int,
    allowed_langs: set[str],
) -> dict:
    company_dir = COMPANIES_DIR / slug
    raw_dir = company_dir / "raw" / "pages"
    extracted_dir = company_dir / "extracted"
    rag_dir = company_dir / "rag"

    raw_dir.mkdir(parents=True, exist_ok=True)
    extracted_dir.mkdir(parents=True, exist_ok=True)
    rag_dir.mkdir(parents=True, exist_ok=True)

    base_domain = urlparse(normalize_url(website)).netloc

    initial_urls = discover_initial_queue(
        website=website,
        seeds=seeds,
        max_pages=max_pages,
        same_domain_only=same_domain_only,
        allowed_langs=allowed_langs,
    )

    # Use a priority frontier so low-value sections (e.g., /blog) can't swallow the entire budget.
    heap: list[tuple[int, int, str]] = []
    seq = 0
    enqueued: set[str] = set()

    diag_counts: dict[str, int] = {
        "initial_urls": 0,
        "discovered_links": 0,
        "enqueued": 0,
        "popped": 0,
        "visited": 0,
        "fetched_html": 0,
        "fetched_failed": 0,
        "rendered_js": 0,
        "extracted_ok": 0,
        "stored_ok": 0,
        "stored_too_short": 0,
        "skipped_duplicate": 0,
        "skipped_cross_domain": 0,
        "skipped_policy": 0,
        "skipped_bucket_cap": 0,
    }

    skipped_samples: dict[str, list[str]] = {}
    def _add_skip(reason: str, url: str) -> None:
        if not reason:
            reason = "unknown"
        diag_counts["skipped_policy"] += 1
        lst = skipped_samples.setdefault(reason, [])
        if len(lst) < 30:
            lst.append(url)

    fetched_samples: list[str] = []

    diag_counts["initial_urls"] = len(initial_urls)
    for u in initial_urls:
        nu = normalize_url(u)
        if not nu:
            continue
        if same_domain_only and not is_same_domain(nu, base_domain):
            diag_counts["skipped_cross_domain"] += 1
            continue
        r = get_skip_reason(nu, allowed_langs)
        if r:
            _add_skip(r, nu)
            continue
        if nu in enqueued:
            diag_counts["skipped_duplicate"] += 1
            continue
        enqueued.add(nu)
        diag_counts["enqueued"] += 1
        # heapq is min-heap; use negative score for max behavior
        heapq.heappush(heap, (-score_url(nu), seq, nu))
        seq += 1

    bucket_caps = default_bucket_caps(max_pages)
    bucket_counts: dict[str, int] = {k: 0 for k in bucket_caps.keys()}

    visited: set[str] = set()
    pages_meta: list[dict] = []
    extracted_count = 0

    # JS 渲染兜底（可选）
    pw = None
    browser = None
    page = None

    js_available = False
    if js_fallback or js_only:
        try:
            from playwright.sync_api import sync_playwright  # type: ignore

            pw = sync_playwright().start()
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page(user_agent=USER_AGENT)
            js_available = True
        except Exception:
            js_available = False
            pw = None
            browser = None
            page = None

    def fetch_html_requests(url: str) -> Optional[str]:
        resp = _requests_get(url, timeout=30)
        if not resp:
            return None

        # Allow HTML bodies even when status is not 200 (some modern sites return 404 with a full HTML page).
        ct = (resp.headers.get("content-type") or "").lower()
        if ct and ("text/html" not in ct and "application/xhtml+xml" not in ct):
            # Not HTML
            return None

        html = _response_text(resp) or ""
        html = replace_cloudflare_emails(html)

        if not html.strip():
            return None

        # If it's clearly an error page with no useful content, skip.
        # Otherwise, keep it for link discovery / extraction.
        if resp.status_code >= 500:
            return None

        return html

    def fetch_html_js(url: str) -> Optional[str]:
        if not js_available or page is None:
            return None
        try:
            page.goto(url, wait_until=js_wait_until, timeout=js_timeout_ms)
            html = page.content() or ""
            html = replace_cloudflare_emails(html)
            return html
        except Exception:
            return None

    try:
        while heap and len(pages_meta) < max_pages:
            url = normalize_url(heapq.heappop(heap)[2])
            diag_counts["popped"] += 1
            if not url:
                _add_skip("bad_url", url)
                continue
            if url in visited:
                diag_counts["skipped_duplicate"] += 1
                continue
            if same_domain_only and not is_same_domain(url, base_domain):
                diag_counts["skipped_cross_domain"] += 1
                continue
            r = get_skip_reason(url, allowed_langs)
            if r:
                _add_skip(r, url)
                continue

            b = bucket_url(url)
            cap = bucket_caps.get(b, max_pages)
            if bucket_counts.get(b, 0) >= cap and b != "other":
                diag_counts["skipped_bucket_cap"] += 1
                continue

            visited.add(url)
            diag_counts["visited"] += 1
            # count toward bucket budget once we decide to fetch
            b = bucket_url(url)
            bucket_counts[b] = bucket_counts.get(b, 0) + 1

            rendered = False
            html = None

            if js_only:
                html = fetch_html_js(url)
                rendered = bool(html)
                if rendered:
                    diag_counts["rendered_js"] += 1
            else:
                html = fetch_html_requests(url)
                rendered = False  # keep explicit

            if html is not None:
                diag_counts["fetched_html"] += 1
            else:
                diag_counts["fetched_failed"] += 1

            if html is None:
                # requests 失败：尝试 js
                if js_fallback:
                    js_html = fetch_html_js(url)
                    if js_html:
                        html = js_html
                        rendered = True
                        diag_counts["rendered_js"] += 1
                if html is None:
                    continue

            # 先抽取一次
            text = extract(html, url=url) or ""
            if text.strip():
                diag_counts["extracted_ok"] += 1

            # JS 兜底：当文本很少且页面看起来像 SPA/JS-heavy 时，再渲染抓取
            if (
                not js_only
                and js_fallback
                and js_available
                and (len((text or "").strip()) < max(50, min_chars // 2))
                and looks_js_heavy(html)
            ):
                js_html = fetch_html_js(url)
                if js_html:
                    html = js_html
                    rendered = True
                    diag_counts["rendered_js"] += 1
                    text = extract(html, url=url) or ""

            title = extract_title(html)

            page_id = len(pages_meta) + 1
            raw_filename = f"{page_id:03d}.html"
            text_filename = f"{page_id:03d}.txt"

            raw_path = raw_dir / raw_filename
            raw_path.write_text(html, encoding="utf-8")

            cleaned_text = (text or "").strip()

            # 语言兜底：若页面正文包含日文假名或韩文 Hangul，直接不入库（避免 Geo/IP/地区路由污染）
            if cleaned_text and re.search(r"[\u3040-\u30ff\uac00-\ud7af]", cleaned_text):
                cleaned_text = ""

            if cleaned_text and len(cleaned_text) >= max(0, min_chars):
                extracted_count += 1
                diag_counts["stored_ok"] += 1
                text_path = extracted_dir / text_filename
                save_text(text_path, cleaned_text)
                text_file = f"extracted/{text_filename}"
            else:
                diag_counts["stored_too_short"] += 1
                cleaned_text = ""
                text_file = ""

            pages_meta.append(
                {
                    "id": page_id,
                    "url": url,
                    "raw_file": f"raw/pages/{raw_filename}",
                    "text_file": text_file,
                    "title": title,
                    "text": cleaned_text,
                    "rendered": rendered,
                }
            )
            if len(fetched_samples) < 50:
                fetched_samples.append(url)

            # BFS 扩展链接：用最终 html（若渲染则包含动态链接）
            if len(pages_meta) < max_pages:
                for link in extract_links(html, url):
                    diag_counts["discovered_links"] += 1
                    if same_domain_only and not is_same_domain(link, base_domain):
                        diag_counts["skipped_cross_domain"] += 1
                        continue
                    r = get_skip_reason(link, allowed_langs)
                    if r:
                        _add_skip(r, link)
                        continue
                    if link in visited or link in enqueued:
                        diag_counts["skipped_duplicate"] += 1
                        continue

                    # Apply bucket caps early: still allow a few, but don't flood the frontier
                    lb = bucket_url(link)
                    if lb != "other" and bucket_counts.get(lb, 0) >= bucket_caps.get(lb, max_pages):
                        diag_counts["skipped_bucket_cap"] += 1
                        continue

                    enqueued.add(link)
                    diag_counts["enqueued"] += 1
                    heapq.heappush(heap, (-score_url(link), seq, link))
                    seq += 1

            time.sleep(max(sleep_seconds, 0))

    finally:
        # 关闭 playwright
        try:
            if page is not None:
                page.close()
        except Exception:
            pass
        try:
            if browser is not None:
                browser.close()
        except Exception:
            pass
        try:
            if pw is not None:
                pw.stop()
        except Exception:
            pass

    fetched_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    sources_meta = {
        "slug": slug,
        "name": name,
        "website": website,
        "fetched_at": fetched_at,
        "pages": [
            {
                "id": page["id"],
                "url": page["url"],
                "raw_file": page["raw_file"],
                "text_file": page["text_file"],
                "title": page.get("title", ""),
                "rendered": bool(page.get("rendered", False)),
            }
            for page in pages_meta
        ],
    }

    (company_dir / "sources_meta.json").write_text(
        json.dumps(sources_meta, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    build_sources_md(company_dir, name, website, fetched_at, pages_meta)

    # Debug: crawl distribution snapshot (helps diagnose "all blog" issues)
    try:
        debug = {
            "max_pages": max_pages,
            "bucket_caps": bucket_caps,
            "bucket_counts": bucket_counts,
            "fetched": len(pages_meta),
            "extracted": extracted_count,
            "diagnostics": diag_counts,
            "fetched_samples": fetched_samples,
            "skipped_samples": skipped_samples,
        }
        (company_dir / "crawl_debug.json").write_text(
            json.dumps(debug, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception:
        pass

    return {
        "fetched": len(pages_meta),
        "extracted": extracted_count,
        "company_dir": company_dir,
        "sources_meta": sources_meta,
    }


def generate_faq(
    slug: str, name: str, website: str, config: dict, output_path: Path
) -> dict:
    from app.rag import retrieve

    questions = [
        "你们是做什么的？",
        "公司能帮助客户什么/解决什么问题？",
        "主要产品/服务有哪些？",
        "典型客户/行业？",
        "典型使用场景/案例？",
        "如何联系（邮箱/电话/地址/表单）？",
        "定价/试用（若无写“未提及”）？",
        "合规/安全（若无写“未提及”）？",
    ]

    base_url = str(config.get("OLLAMA_BASE_URL", "")).rstrip("/")
    model = str(config.get("LLM_MODEL", ""))

    items = []
    for idx, question in enumerate(questions, start=1):
        top_k = int(config.get("TOP_K", 8))
        sources = retrieve(slug, question, top_k=top_k, config=config)
        context = "\n".join(f"[{item['idx']}] {item['text']}" for item in sources)
        prompt = (
            "请基于资料回答问题，若资料未提及请回答“未提及/不确定”。\n"
            "答案需要带来源编号，如 [1] 或 [1][3]。\n\n"
            f"资料:\n{context}\n\n"
            f"问题: {question}\n"
        )

        payload = {
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": "你是公司官网资料整理员，要求简洁、结构化，不能编造。",
                },
                {"role": "user", "content": prompt},
            ],
            "stream": False,
        }

        answer_text = "未提及/不确定。"
        try:
            response = requests.post(
                f"{base_url}/api/chat",
                json=payload,
                timeout=120,
            )
            if response.status_code == 200:
                data = response.json()
                answer_text = data.get("message", {}).get("content", "").strip()
        except requests.RequestException:
            answer_text = "未提及/不确定。"

        faq_sources = []
        for src in sources:
            snippet = build_snippet(src.get("text", ""), max_len=110)
            url = src.get("url", "")
            faq_sources.append(
                {
                    "title": src.get("title", ""),
                    "url": url,
                    "deep_link": build_deep_link(url, snippet),
                    "snippet": snippet,
                    "chunk_id": src.get("chunk_id", ""),
                    "score": src.get("score", 0.0),
                }
            )

        items.append(
            {
                "id": f"faq-{idx:02d}",
                "question": question,
                "answer_md": answer_text or "未提及/不确定。",
                "sources": faq_sources,
            }
        )

    faq = {
        "slug": slug,
        "name": name,
        "website": website,
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "items": items,
    }

    output_path.write_text(json.dumps(faq, ensure_ascii=False, indent=2), encoding="utf-8")
    return faq


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="导入公司公开网页到 RAG")
    parser.add_argument("--slug", required=True, help="公司标识（小写）")
    parser.add_argument("--name", required=True, help="公司名称")
    parser.add_argument("--website", required=True, help="公司官网")
    parser.add_argument("--seed", action="append", required=True, help="起始 URL，可多次传入")
    parser.add_argument("--max-pages", type=int, default=50, help="最多抓取页面数")
    parser.add_argument(
        "--keep-langs",
        type=str,
        default=DEFAULT_KEEP_LANGS,
        help="只爬这些语言版本（默认 en,zh-cn；zh/zh-hans 归一为 zh-cn；en-us/en-gb 归一为 en）",
    )

    try:
        from argparse import BooleanOptionalAction  # type: ignore

        parser.add_argument(
            "--same-domain-only",
            action=BooleanOptionalAction,
            default=True,
            help="只抓同域名页面（默认 true）",
        )
        parser.add_argument(
            "--js-fallback",
            action=BooleanOptionalAction,
            default=True,
            help="requests 抓不到/内容过短时，启用 Playwright JS 渲染兜底（默认 true）",
        )
        parser.add_argument(
            "--js-only",
            action=BooleanOptionalAction,
            default=False,
            help="所有页面都使用 Playwright 渲染抓取（更慢但覆盖更好）",
        )
    except ImportError:
        parser.add_argument(
            "--same-domain-only",
            action="store_true",
            default=True,
            help="只抓同域名页面（默认 true）",
        )
        parser.add_argument(
            "--no-same-domain-only",
            action="store_false",
            dest="same_domain_only",
            help="允许跨域名抓取",
        )
        parser.add_argument(
            "--js-fallback",
            action="store_true",
            default=True,
            help="启用 JS 渲染兜底",
        )
        parser.add_argument(
            "--no-js-fallback",
            action="store_false",
            dest="js_fallback",
            help="禁用 JS 渲染兜底",
        )
        parser.add_argument(
            "--js-only",
            action="store_true",
            default=False,
            help="所有页面都使用 JS 渲染抓取",
        )

    parser.add_argument("--sleep", type=float, default=1.0, help="抓取间隔（秒）")
    parser.add_argument(
        "--min-chars",
        type=int,
        default=200,
        help="正文最小字符数（信息密度优先：低于该值不入库，默认 200）",
    )
    parser.add_argument(
        "--js-wait-until",
        type=str,
        default="networkidle",
        help="Playwright goto 等待条件：load/domcontentloaded/networkidle（默认 networkidle）",
    )
    parser.add_argument(
        "--js-timeout-ms",
        type=int,
        default=90000,
        help="Playwright goto 超时毫秒（默认 90000）",
    )
    parser.add_argument(
        "--gen-faq",
        type=str,
        default="true",
        help="是否生成 FAQ 缓存（true/false）",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    slug = args.slug.strip()
    if not slug or slug != slug.lower() or " " in slug:
        raise SystemExit("slug 必须是小写且不能包含空格")

    company_dir = COMPANIES_DIR / slug
    company_dir.mkdir(parents=True, exist_ok=True)

    allowed_langs = parse_keep_langs(args.keep_langs)

    report = crawl_site(
        slug=slug,
        name=args.name.strip(),
        website=args.website.strip(),
        seeds=args.seed,
        max_pages=args.max_pages,
        same_domain_only=args.same_domain_only,
        sleep_seconds=args.sleep,
        min_chars=args.min_chars,
        js_fallback=args.js_fallback,
        js_only=args.js_only,
        js_wait_until=str(args.js_wait_until).strip() or "networkidle",
        js_timeout_ms=int(args.js_timeout_ms),
        allowed_langs=allowed_langs,
    )

    print("导入完成:")
    print(f"- 抓取页面数: {report['fetched']}")
    print(f"- 抽取成功数(>=min-chars): {report['extracted']}")

    try:
        from app.config import load_config
        from app.rag import build_index

        config = load_config()
        build_index(slug, config=config)
        print("- 索引状态: 成功")
        if str(args.gen_faq).strip().lower() != "false":
            faq_path = company_dir / "faq.json"
            generate_faq(
                slug=slug,
                name=args.name.strip(),
                website=args.website.strip(),
                config=config,
                output_path=faq_path,
            )
            print("- FAQ 状态: 成功")
    except Exception as exc:
        print(f"- 索引状态: 失败 ({exc})")


if __name__ == "__main__":
    main()
