#!/usr/bin/env bash
# Usage:
#   bash sizecheck.sh [APP_NAME] [GENERATE_HTML] [GENERATE_AI] [GENERATE_ASSESS]
#   APP_NAME=myapp GENERATE_HTML=false GENERATE_AI=true GENERATE_ASSESS=false bash sizecheck.sh
#
# APP_NAME        : レポートに表示するアプリケーション名 (default: quarkusdroneshop)
# GENERATE_HTML   : true/false でHTMLレポート(report.html)生成有無を切り替え (default: true)
# GENERATE_AI     : true/false でAI Development節(git由来のLines Added/Deleted・
#                   Refactoring Ratio・AI共著コミット比率)の追加有無を切り替え (default: false)
#                   直下に ai-metrics.json があれば併せて読み込む(無ければ外部メトリクスは省略)。
#                   大きなベンダー取り込み履歴があると重くなるため --ai-since で直近90日に限定している。
# GENERATE_ASSESS : true/false でOverall Assessment節(Maintainability/Architecture/
#                   Cloud Native/Documentation/AI Readinessのスコアカード)の追加有無を
#                   切り替え (default: true)。直下に assessment.json があれば重み設定として読み込む。
set -euo pipefail

APP_NAME="${1:-${APP_NAME:-quarkusdroneshop}}"
GENERATE_HTML="${2:-${GENERATE_HTML:-true}}"
GENERATE_AI="${3:-${GENERATE_AI:-false}}"
GENERATE_ASSESS="${4:-${GENERATE_ASSESS:-true}}"

echo "============================================================"
echo " Software Size Report"
echo "------------------------------------------------------------"
echo " Application  : ${APP_NAME}"
echo " Generate HTML: ${GENERATE_HTML}"
echo " Generate AI  : ${GENERATE_AI}"
echo " Generate Assess: ${GENERATE_ASSESS}"
echo "============================================================"

ARGS=(software_size.py .. --name "${APP_NAME}" --weights weights.json --effort --productivity productivity.json)

if [[ "${GENERATE_AI}" == "true" ]]; then
  ARGS+=(--ai --ai-since "90 days ago")
  if [[ -f ai-metrics.json ]]; then
    ARGS+=(--ai-metrics ai-metrics.json)
  fi
fi

if [[ "${GENERATE_ASSESS}" == "true" ]]; then
  ARGS+=(--assess)
  if [[ -f assessment.json ]]; then
    ARGS+=(--assessment assessment.json)
  fi
fi

if [[ "${GENERATE_HTML}" == "true" ]]; then
  ARGS+=(--html report.html)
fi

python3 "${ARGS[@]}"
