#!/usr/bin/env bash
# scripts/run_benchmarks.sh
# Start each framework server, run wrk benchmarks, save results to JSON/CSV.
# Requires: wrk, python3.14
# Run from benchmark_frameworks/
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RESULTS_DIR="$ROOT/benchmarks/results"
SCRIPTS_DIR="$ROOT/scripts"
mkdir -p "$RESULTS_DIR"

CONCURRENCY=(10 50 100 200)
DURATION=30
THREADS=4

log()  { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
info() { printf '    %s\n' "$*"; }

# ---------------------------------------------------------------------------
# wait_for_server <url> <timeout_secs>
# ---------------------------------------------------------------------------
wait_for_server() {
    local url="$1" timeout="${2:-15}" elapsed=0
    until curl -sf "$url" > /dev/null 2>&1; do
        sleep 0.5
        elapsed=$((elapsed + 1))
        if [[ $elapsed -ge $((timeout * 2)) ]]; then
            echo "  [ERROR] Server at $url did not start within ${timeout}s" >&2
            return 1
        fi
    done
}

# ---------------------------------------------------------------------------
# run_wrk_scenario <framework> <endpoint> <url> <concurrency>
# Runs wrk and appends a JSON result line to $RESULTS_DIR/raw.jsonl
# ---------------------------------------------------------------------------
run_wrk_scenario() {
    local framework="$1" endpoint="$2" url="$3" concurrency="$4"
    local extra_args=""
    if [[ "$endpoint" == "create_post" ]]; then
        extra_args="-s $SCRIPTS_DIR/post.lua"
    fi

    info "wrk -t${THREADS} -c${concurrency} -d${DURATION}s $extra_args $url"
    local output
    output=$(wrk -t"${THREADS}" -c"${concurrency}" -d"${DURATION}s" \
        --latency $extra_args "$url" 2>&1)

    # Delegate parsing to Python
    python3.14 - <<PYEOF
import json, re, sys

output = """$output"""

def parse_ms(val):
    val = val.strip()
    if val.endswith('us'):
        return float(val[:-2]) / 1000
    elif val.endswith('ms'):
        return float(val[:-2])
    elif val.endswith('s'):
        return float(val[:-1]) * 1000
    return float(val)

latency_match  = re.search(r'Latency\s+(\S+)\s+\S+\s+\S+', output)
rps_match      = re.search(r'Requests/sec:\s+(\S+)', output)
transfer_match = re.search(r'Transfer/sec:\s+(\S+)(MB|KB|GB)', output)
p95_match      = re.search(r'95%\s+(\S+)', output)
p99_match      = re.search(r'99%\s+(\S+)', output)
err_match      = re.search(r'Socket errors.*?(\d+) timeouts', output)
req_match      = re.search(r'(\d[\d,]*) requests in', output)
non2xx_match   = re.search(r'Non-2xx or 3xx responses:\s*(\d+)', output)

total_requests = int(req_match.group(1).replace(',', '')) if req_match else 0
errors         = int(non2xx_match.group(1)) if non2xx_match else 0
error_rate     = round(errors / total_requests * 100, 4) if total_requests else 0.0

def to_mbs(val, unit):
    v = float(val)
    if unit == 'KB': return round(v / 1024, 3)
    if unit == 'GB': return round(v * 1024, 3)
    return round(v, 3)

throughput = 0.0
if transfer_match:
    throughput = to_mbs(transfer_match.group(1), transfer_match.group(2))

record = {
    "framework":    "$framework",
    "endpoint":     "$endpoint",
    "concurrency":  $concurrency,
    "requests_per_second": round(float(rps_match.group(1).replace('k','e3')), 2) if rps_match else 0.0,
    "avg_latency_ms":  round(parse_ms(latency_match.group(1)), 3) if latency_match else 0.0,
    "p95_latency_ms":  round(parse_ms(p95_match.group(1)), 3) if p95_match else 0.0,
    "p99_latency_ms":  round(parse_ms(p99_match.group(1)), 3) if p99_match else 0.0,
    "throughput_mb_sec": throughput,
    "error_rate":   error_rate,
}

with open("$RESULTS_DIR/raw.jsonl", "a") as f:
    f.write(json.dumps(record) + "\n")

print(f"    RPS={record['requests_per_second']}  avg={record['avg_latency_ms']}ms  "
      f"p95={record['p95_latency_ms']}ms  p99={record['p99_latency_ms']}ms  "
      f"err={record['error_rate']}%")
PYEOF
}

# ---------------------------------------------------------------------------
# benchmark_framework <name> <port> <dir> <start_cmd>
# ---------------------------------------------------------------------------
benchmark_framework() {
    local name="$1" port="$2" dir="$3" start_cmd="$4"

    log "Benchmarking $name (port $port)"

    # Start server
    cd "$ROOT/$dir"
    eval "source .venv/bin/activate && $start_cmd &"
    local server_pid=$!
    deactivate 2>/dev/null || true

    info "Waiting for server …"
    if ! wait_for_server "http://localhost:${port}/posts/1" 20; then
        kill "$server_pid" 2>/dev/null || true
        return 1
    fi
    info "Server ready (pid $server_pid)"

    for c in "${CONCURRENCY[@]}"; do
        info "--- GET /posts/1  concurrency=$c"
        run_wrk_scenario "$name" "get_post" "http://localhost:${port}/posts/1" "$c"

        info "--- POST /posts   concurrency=$c"
        run_wrk_scenario "$name" "create_post" "http://localhost:${port}/posts" "$c"
    done

    kill "$server_pid" 2>/dev/null || true
    wait "$server_pid" 2>/dev/null || true
    sleep 1
    info "$name done."
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
# Clear previous raw results
rm -f "$RESULTS_DIR/raw.jsonl"

benchmark_framework "OpenViper" 8000 "openviper_blog" \
    "openviper run app:app --port 8000 --workers 4"

benchmark_framework "FastAPI" 8001 "fastapi_blog" \
    "uvicorn main:app --port 8001 --workers 4 --log-level warning"

benchmark_framework "Flask" 8002 "flask_blog" \
    "gunicorn -w 4 -b 127.0.0.1:8002 app:app --log-level warning"

benchmark_framework "Django" 8003 "django_blog" \
    "gunicorn -w 4 -b 127.0.0.1:8003 django_blog.wsgi:application --log-level warning"

# Convert JSONL → JSON array + CSV
python3.14 - <<'PYEOF'
import json, csv
from pathlib import Path

results_dir = Path("benchmarks/results")
raw = [json.loads(l) for l in (results_dir / "raw.jsonl").read_text().splitlines() if l.strip()]

# JSON
(results_dir / "results.json").write_text(json.dumps(raw, indent=2))

# CSV
if raw:
    with open(results_dir / "results.csv", "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=raw[0].keys())
        writer.writeheader()
        writer.writerows(raw)

print(f"\nSaved {len(raw)} result rows to benchmarks/results/")
PYEOF

log "All benchmarks complete. Results in benchmarks/results/"
