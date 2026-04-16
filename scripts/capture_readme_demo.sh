#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PORT="${FAFYCAT_README_DEMO_PORT:-8010}"
HOST="127.0.0.1"
BASE_URL="http://${HOST}:${PORT}"
DATA_DIR="${TMPDIR%/}/fafycat-readme-demo-data"
RAW_DIR="${ROOT_DIR}/docs/media/.raw"
OUTPUT_DIR="${ROOT_DIR}/docs/media"
DEMO_CSV="${OUTPUT_DIR}/demo-import.csv"
SERVER_LOG="${RAW_DIR}/server.log"
NODE_TOOLS_DIR="${RAW_DIR}/node-tools"

cleanup() {
    if [[ -n "${SERVER_PID:-}" ]] && kill -0 "${SERVER_PID}" >/dev/null 2>&1; then
        kill "${SERVER_PID}" >/dev/null 2>&1 || true
        wait "${SERVER_PID}" >/dev/null 2>&1 || true
    fi
}

trap cleanup EXIT

rm -rf "${DATA_DIR}" "${RAW_DIR}"
mkdir -p "${RAW_DIR}"

uv run fafycat serve --dev --data-dir "${DATA_DIR}" --host "${HOST}" --port "${PORT}" >"${SERVER_LOG}" 2>&1 &
SERVER_PID=$!

python3 - "${BASE_URL}" <<'PY'
import sys
import time
import urllib.error
import urllib.request

base_url = sys.argv[1]

for _ in range(60):
    try:
        with urllib.request.urlopen(base_url, timeout=2):
            raise SystemExit(0)
    except urllib.error.URLError:
        time.sleep(1)

raise SystemExit("Server did not become ready in time")
PY

JOB_ID="$(
python3 - "${BASE_URL}" <<'PY'
import json
import sys
import urllib.request

request = urllib.request.Request(f"{sys.argv[1]}/api/ml/retrain", method="POST")
with urllib.request.urlopen(request, timeout=30) as response:
    payload = json.load(response)

print(payload["job_id"])
PY
)"

python3 - "${BASE_URL}" "${JOB_ID}" <<'PY'
import json
import sys
import time
import urllib.request

base_url = sys.argv[1]
job_id = sys.argv[2]
status_url = f"{base_url}/api/ml/training-status/{job_id}"

for _ in range(90):
    with urllib.request.urlopen(status_url, timeout=30) as response:
        payload = json.load(response)
    if payload.get("status") == "completed":
        result = payload.get("result") or {}
        if result.get("status") != "success":
            raise SystemExit(f"Training failed: {payload}")
        raise SystemExit(0)
    time.sleep(1)

raise SystemExit("Training did not complete in time")
PY

npm install --prefix "${NODE_TOOLS_DIR}" --no-save --no-package-lock playwright >/dev/null
NODE_PATH="${NODE_TOOLS_DIR}/node_modules" npx -y playwright install chromium >/dev/null
NODE_PATH="${NODE_TOOLS_DIR}/node_modules" node "${ROOT_DIR}/scripts/capture_readme_demo.cjs" \
    --base-url "${BASE_URL}" \
    --output-dir "${RAW_DIR}" \
    --demo-csv "${DEMO_CSV}"

uv run python "${ROOT_DIR}/scripts/annotate_readme_demo_assets.py" "${RAW_DIR}" "${OUTPUT_DIR}"

echo "README demo assets written to ${OUTPUT_DIR}"
