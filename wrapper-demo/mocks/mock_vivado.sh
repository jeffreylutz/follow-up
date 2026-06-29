#!/usr/bin/env bash
# Mock Xilinx Vivado: prints, shows it received the injected env, then "builds".
set -euo pipefail
echo "[mock-vivado] starting (pid $$) args: $*"
echo "[mock-vivado] XILINXD_LICENSE_FILE=${XILINXD_LICENSE_FILE:-<unset>}"
sleep "${MOCK_VIVADO_SECONDS:-5}"
echo "[mock-vivado] done (pid $$)"
