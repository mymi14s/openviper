#!/usr/bin/env bash
set -euo pipefail

# OpenViper Quality Check Script
# Runs ruff, mypy, and flake8 to ensure code quality.

SRC="openviper"
PASS=0
FAIL=0

run_check() {
    local name="$1"
    shift
    echo "--- Running ${name} ---"
    if "$@"; then
        echo "  ✓ ${name}: Passed"
        PASS=$((PASS + 1))
    else
        echo "  ✗ ${name}: Failed"
        FAIL=$((FAIL + 1))
    fi
}

echo ""
run_check "Ruff (lint)"       ruff check "${SRC}"
run_check "Ruff (format)"    ruff format --check "${SRC}"
run_check "Mypy"             mypy -p "${SRC}"
run_check "Flake8"           flake8 "${SRC}"

echo ""
echo "--- Summary ---"
if [ "${FAIL}" -eq 0 ]; then
    echo "  All ${PASS} checks passed."
    exit 0
else
    echo "  ${FAIL} check(s) failed, ${PASS} passed."
    exit 1
fi
