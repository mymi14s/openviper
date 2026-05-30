#!/usr/bin/env bash
set -euo pipefail

# OpenViper HTTP Load Test
# Usage: ./load_test.sh [URL] [TOTAL_REQUESTS] [CONCURRENCY]

URL="${1:-http://localhost}"
TOTAL="${2:-1000}"
CONCURRENT="${3:-100}"

printf "Load testing %s: %s requests, %s concurrent\n" "${URL}" "${TOTAL}" "${CONCURRENT}"

START=$(date +%s%N)

OK=0
FAIL=0
while IFS= read -r code; do
    if [ "${code}" -ge 200 ] && [ "${code}" -lt 400 ]; then
        OK=$((OK + 1))
    else
        FAIL=$((FAIL + 1))
    fi
done < <(
    seq "${TOTAL}" | xargs -P "${CONCURRENT}" -I{} \
        curl -s -o /dev/null -w '%{http_code}\n' "${URL}"
)

END=$(date +%s%N)
ELAPSED=$(( (END - START) / 1000000 ))

printf "\n--- Results ---\n"
printf "  Total:    %s\n" "${TOTAL}"
printf "  OK:       %s\n" "${OK}"
printf "  Failed:   %s\n" "${FAIL}"
printf "  Time:     %s ms\n" "${ELAPSED}"
if [ "${ELAPSED}" -gt 0 ]; then
    printf "  RPS:      %s\n" "$(( TOTAL * 1000 / ELAPSED ))"
fi

if [ "${FAIL}" -gt 0 ]; then
    exit 1
fi
