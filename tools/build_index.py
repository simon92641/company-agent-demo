import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.config import load_config  # noqa: E402
from app.rag import build_index  # noqa: E402


def main() -> None:
    if len(sys.argv) < 2:
        print("用法: python tools/build_index.py <company>")
        sys.exit(1)

    company = sys.argv[1]
    config = load_config()
    try:
        build_index(company, config=config)
    except Exception as exc:
        print(f"构建索引失败: {exc}")
        sys.exit(1)

    print(f"索引构建完成: {company}")


if __name__ == "__main__":
    main()
