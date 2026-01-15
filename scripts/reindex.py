import sys
import subprocess
from pathlib import Path
import os

ROOT = Path(__file__).resolve().parents[1]
COMPANIES = ROOT / "companies"

def list_companies():
    if not COMPANIES.exists():
        raise FileNotFoundError(f"companies 目录不存在: {COMPANIES}")

    companies = []
    for p in COMPANIES.iterdir():
        if not p.is_dir():
            continue
        if (p / "sources.md").exists():
            companies.append(p.name)

    return sorted(companies)

def build(company: str):
    print(f"==> build_index: {company}", flush=True)
    subprocess.check_call([sys.executable, "tools/build_index.py", company], cwd=str(ROOT))

if __name__ == "__main__":
    args = sys.argv[1:]

    if args and args[0] == "--list":
        try:
            comps = list_companies()
        except Exception as e:
            print(f"[reindex] 无法读取 companies 目录: {e}", file=sys.stderr)
            sys.exit(2)
        if not comps:
            print("[reindex] 未找到任何可建立索引的公司：请确认 companies/<company>/sources.md 存在")
        else:
            print("\n".join(comps))
        sys.exit(0)

    if args and args[0] == "--all":
        try:
            comps = list_companies()
        except Exception as e:
            print(f"[reindex] 无法读取 companies 目录: {e}", file=sys.stderr)
            sys.exit(2)

        if not comps:
            print("[reindex] --all 但未找到任何公司（需要 companies/<company>/sources.md）")
            print("[reindex] 你可以运行：find companies -maxdepth 2 -name sources.md -print")
            sys.exit(1)

        for c in comps:
            build(c)
    elif args:
        build(args[0])
    else:
        print("用法：python scripts/reindex.py <company>  或  python scripts/reindex.py --all  或  python scripts/reindex.py --list")
