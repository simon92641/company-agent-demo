#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LIST="$ROOT/companies_to_ingest.tsv"
LOG_DIR="$ROOT/logs"
mkdir -p "$LOG_DIR"

MASTER_LOG="$LOG_DIR/batch_$(date +%Y%m%d_%H%M%S).log"
echo "[batch] start: $(date) root=$ROOT" | tee -a "$MASTER_LOG"

# 检查 Ollama（否则索引/FAQ 会失败）
if ! curl -s "http://localhost:11434/api/tags" >/dev/null 2>&1; then
  echo "[batch] ERROR: Ollama not reachable at http://localhost:11434" | tee -a "$MASTER_LOG"
  exit 1
fi

while IFS=$'\t' read -r slug name website seed max_pages js_only min_chars sleep_sec; do
  [[ -z "${slug:-}" ]] && continue
  [[ "${slug:0:1}" == "#" ]] && continue

  company_dir="$ROOT/companies/$slug"
  run_log="$LOG_DIR/${slug}_$(date +%Y%m%d_%H%M%S).log"

  echo "[batch][$slug] start: $(date)" | tee -a "$MASTER_LOG" | tee -a "$run_log"

  # 你说“文件都删了”——我这里直接强制清理，保证每次重建
  rm -rf "$company_dir"

  cmd=(python "$ROOT/scripts/ingest_company.py"
    --slug "$slug"
    --name "$name"
    --website "$website"
    --seed "$seed"
    --max-pages "$max_pages"
    --min-chars "$min_chars"
    --sleep "$sleep_sec"
    --keep-langs "en,zh-cn"
    --gen-faq true
  )

  # js_only=1 时全站渲染（更慢但更全）
  if [[ "$js_only" == "1" ]]; then
    cmd+=(--js-only true)
  fi

  echo "[batch][$slug] cmd: ${cmd[*]}" | tee -a "$MASTER_LOG" | tee -a "$run_log"

  # 失败重试 1 次
  if ! "${cmd[@]}" 2>&1 | tee -a "$run_log"; then
    echo "[batch][$slug] failed once, retrying..." | tee -a "$MASTER_LOG" | tee -a "$run_log"
    sleep 3
    "${cmd[@]}" 2>&1 | tee -a "$run_log" || {
      echo "[batch][$slug] FAILED twice, continue next." | tee -a "$MASTER_LOG" | tee -a "$run_log"
      continue
    }
  fi

  # 验收 FAQ 是否生成
  if [[ -f "$company_dir/faq.json" ]]; then
    echo "[batch][$slug] OK: faq.json generated" | tee -a "$MASTER_LOG"
  else
    echo "[batch][$slug] WARN: faq.json missing (check log: $run_log)" | tee -a "$MASTER_LOG"
  fi

done < "$LIST"

echo "[batch] done: $(date)" | tee -a "$MASTER_LOG"