#!/usr/bin/env bash
# Usage:
#   bash sizecheck.sh [APP_NAME] [GENERATE_HTML]
#   APP_NAME=myapp GENERATE_HTML=false bash sizecheck.sh
#
# APP_NAME       : レポートに表示するアプリケーション名 (default: quarkusdroneshop)
# GENERATE_HTML  : true/false でHTMLレポート(report.html)生成有無を切り替え (default: true)
set -euo pipefail

APP_NAME="${1:-${APP_NAME:-quarkusdroneshop}}"
GENERATE_HTML="${2:-${GENERATE_HTML:-true}}"

echo "============================================================"
echo " Software Size Report"
echo "------------------------------------------------------------"
echo " Application  : ${APP_NAME}"
echo " Generate HTML: ${GENERATE_HTML}"
echo "============================================================"

ARGS=(software_size.py .. --name "${APP_NAME}" --weights weights.json --effort --productivity productivity.json)

if [[ "${GENERATE_HTML}" == "true" ]]; then
  ARGS+=(--html report.html)
fi

python3 "${ARGS[@]}"
