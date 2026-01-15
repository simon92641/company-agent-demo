import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.config import load_config  # noqa: E402
from app.rag import build_index  # noqa: E402

COMPANIES_DIR = PROJECT_ROOT / "companies"


def find_companies() -> list[str]:
    if not COMPANIES_DIR.exists():
        return []
    companies: list[str] = []
    for path in COMPANIES_DIR.iterdir():
        if path.is_dir() and (path / "sources.md").exists():
            companies.append(path.name)
    return sorted(companies)


def main() -> None:
    companies = find_companies()
    if not companies:
        print("未找到可用的公司目录 (需要包含 sources.md)")
        sys.exit(1)

    config = load_config()
    failures: list[str] = []

    for slug in companies:
        try:
            build_index(slug, config=config)
            print(f"索引构建完成: {slug}")
        except Exception as exc:
            failures.append(f"{slug}: {exc}")

    if failures:
        print("以下公司构建失败:")
        for item in failures:
            print(f"- {item}")
        sys.exit(1)


if __name__ == "__main__":
    main()
