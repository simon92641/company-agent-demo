import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.config import load_config  # noqa: E402
from scripts.ingest_company import generate_faq  # noqa: E402

COMPANIES_DIR = PROJECT_ROOT / "companies"


def load_meta(company_dir: Path) -> dict:
    meta_path = company_dir / "sources_meta.json"
    if not meta_path.exists():
        return {}
    try:
        return json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def find_companies() -> list[Path]:
    if not COMPANIES_DIR.exists():
        return []
    companies = []
    for path in COMPANIES_DIR.iterdir():
        if path.is_dir() and (path / "sources.md").exists():
            companies.append(path)
    return sorted(companies, key=lambda p: p.name)


def main() -> None:
    companies = find_companies()
    if not companies:
        print("未找到可用的公司目录 (需要包含 sources.md)")
        sys.exit(1)

    config = load_config()
    failures = []

    for company_dir in companies:
        slug = company_dir.name
        meta = load_meta(company_dir)
        name = str(meta.get("name", slug)).strip() or slug
        website = str(meta.get("website", "")).strip()
        faq_path = company_dir / "faq.json"

        try:
            generate_faq(
                slug=slug,
                name=name,
                website=website,
                config=config,
                output_path=faq_path,
            )
            print(f"FAQ 生成完成: {slug}")
        except Exception as exc:
            failures.append(f"{slug}: {exc}")

    if failures:
        print("以下公司 FAQ 生成失败:")
        for item in failures:
            print(f"- {item}")
        sys.exit(1)


if __name__ == "__main__":
    main()
