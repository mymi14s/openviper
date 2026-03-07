#!/usr/bin/env python3.14
"""scripts/run_benchmark.py

Orchestrates the full benchmark:
  1. Start each framework server
  2. Wait for readiness
  3. Run wrk at each concurrency level for GET and POST
  4. Parse output and save results.json + results.csv
  5. Shut down servers cleanly

Usage:
    cd performance_matrix/benchmark_frameworks
    python3.14 scripts/run_benchmark.py
"""

from __future__ import annotations

import csv
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RESULTS_DIR = ROOT / "benchmarks" / "results"
SCRIPTS_DIR = ROOT / "scripts"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

PYTHON = sys.executable
DURATION = 30
THREADS = 4
CONCURRENCY_LEVELS = [10, 50, 100, 200]

FRAMEWORKS = [
    {
        "name": "OpenViper",
        "port": 8000,
        "cwd": ROOT / "openviper_blog",
        "cmd": [
            PYTHON, "-m", "uvicorn", "app:app",
            "--port", "8000",
            "--workers", "4",
            "--log-level", "warning",
        ],
        "env_extra": {"OPENVIPER_SETTINGS_MODULE": "settings"},
    },
    {
        "name": "FastAPI",
        "port": 8001,
        "cwd": ROOT / "fastapi_blog",
        "cmd": [
            PYTHON, "-m", "uvicorn", "main:app",
            "--port", "8001",
            "--workers", "4",
            "--log-level", "warning",
        ],
        "env_extra": {},
    },
    {
        "name": "Flask",
        "port": 8002,
        "cwd": ROOT / "flask_blog",
        "cmd": [
            PYTHON, "-m", "gunicorn",
            "-w", "4",
            "-b", "127.0.0.1:8002",
            "--worker-tmp-dir", "/tmp",
            "--log-level", "warning",
            "app:app",
        ],
        "env_extra": {},
    },
    {
        "name": "Django",
        "port": 8003,
        "cwd": ROOT / "django_blog",
        "cmd": [
            PYTHON, "-m", "gunicorn",
            "-w", "4",
            "-b", "127.0.0.1:8003",
            "--worker-tmp-dir", "/tmp",
            "--log-level", "warning",
            "django_blog.wsgi:application",
        ],
        "env_extra": {"DJANGO_SETTINGS_MODULE": "django_blog.settings"},
    },
]


# ---------------------------------------------------------------------------
# Server management
# ---------------------------------------------------------------------------

def start_server(fw: dict) -> subprocess.Popen:
    env = os.environ.copy()
    env.update(fw.get("env_extra", {}))
    # Ensure the framework directory is in PYTHONPATH so uvicorn workers can find settings.py
    cwd_str = str(fw["cwd"])
    existing_pp = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = f"{cwd_str}:{existing_pp}" if existing_pp else cwd_str
    
    proc = subprocess.Popen(
        fw["cmd"],
        cwd=fw["cwd"],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    return proc


def wait_for_server(port: int, timeout: int = 20) -> bool:
    url = f"http://127.0.0.1:{port}/posts/1"
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1) as r:
                if r.status in (200, 404):
                    return True
        except Exception:
            pass
        time.sleep(0.3)
    return False


def stop_server(proc: subprocess.Popen) -> None:
    if proc.poll() is None:
        proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


# ---------------------------------------------------------------------------
# wrk output parsing
# ---------------------------------------------------------------------------

def _parse_val_ms(val: str) -> float:
    v = val.strip()
    if v.endswith("us"):
        return float(v[:-2]) / 1000
    if v.endswith("ms"):
        return float(v[:-2])
    if v.endswith("s"):
        return float(v[:-1]) * 1000
    return float(v)


def _parse_rps(val: str) -> float:
    v = val.strip().lower()
    if v.endswith("k"):
        return float(v[:-1]) * 1_000
    if v.endswith("m"):
        return float(v[:-1]) * 1_000_000
    return float(v)


def _parse_throughput_mb(val: str, unit: str) -> float:
    v = float(val)
    if unit.upper() == "KB":
        return round(v / 1024, 3)
    if unit.upper() == "GB":
        return round(v * 1024, 3)
    return round(v, 3)


def parse_wrk_output(output: str, framework: str, endpoint: str, concurrency: int) -> dict:
    # Anchor percentile patterns to line-start to prevent cross-line matches
    # (wrk thread-stats stdev column ends lines with e.g. "90.00%" — distinct
    # from the latency-distribution lines which use bare integers like "90%")
    latency_m = re.search(r"Latency\s+(\S+)\s+\S+\s+\S+", output)
    rps_m     = re.search(r"Requests/sec:\s+(\S+)", output)
    xfer_m    = re.search(r"Transfer/sec:\s+(\S+)(MB|KB|GB)", output)
    p90_m     = re.search(r"^\s+90%\s+(\S+)", output, re.MULTILINE)
    p99_m     = re.search(r"^\s+99%\s+(\S+)", output, re.MULTILINE)
    req_m     = re.search(r"([\d,]+) requests in", output)
    non2xx_m  = re.search(r"Non-2xx or 3xx responses:\s*(\d+)", output)

    total = int(req_m.group(1).replace(",", "")) if req_m else 0
    errors = int(non2xx_m.group(1)) if non2xx_m else 0
    error_rate = round(errors / total * 100, 4) if total else 0.0

    try:
        p90_val = round(_parse_val_ms(p90_m.group(1)), 3) if p90_m else 0.0
    except (ValueError, AttributeError):
        p90_val = 0.0
    try:
        p99_val = round(_parse_val_ms(p99_m.group(1)), 3) if p99_m else 0.0
    except (ValueError, AttributeError):
        p99_val = 0.0

    return {
        "framework":           framework,
        "endpoint":            endpoint,
        "concurrency":         concurrency,
        "requests_per_second": round(_parse_rps(rps_m.group(1)), 2) if rps_m else 0.0,
        "avg_latency_ms":      round(_parse_val_ms(latency_m.group(1)), 3) if latency_m else 0.0,
        "p90_latency_ms":      p90_val,
        "p99_latency_ms":      p99_val,
        "throughput_mb_sec":   _parse_throughput_mb(xfer_m.group(1), xfer_m.group(2)) if xfer_m else 0.0,
        "error_rate":          error_rate,
    }


# ---------------------------------------------------------------------------
# wrk execution
# ---------------------------------------------------------------------------

WRK = shutil.which("wrk") or "wrk"


def run_wrk(url: str, concurrency: int, lua_script: str | None = None) -> str:
    cmd = [
        WRK,
        f"-t{THREADS}",
        f"-c{concurrency}",
        f"-d{DURATION}s",
        "--latency",
    ]
    if lua_script:
        cmd += ["-s", lua_script]
    cmd.append(url)

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=DURATION + 30)
    return result.stdout + result.stderr


# ---------------------------------------------------------------------------
# Main benchmark loop
# ---------------------------------------------------------------------------

def benchmark_framework(fw: dict, results: list[dict]) -> None:
    name = fw["name"]
    port = fw["port"]
    print(f"\n{'='*60}")
    print(f"  {name}  (port {port})")
    print(f"{'='*60}")

    proc = start_server(fw)
    print(f"  Starting server (pid {proc.pid}) … ", end="", flush=True)

    if not wait_for_server(port):
        print("FAILED to start")
        # Print stderr for diagnosis
        err = proc.stderr.read().decode(errors="replace") if proc.stderr else ""
        print(f"  stderr: {err[:500]}")
        stop_server(proc)
        return
    print("ready")

    try:
        for c in CONCURRENCY_LEVELS:
            # GET /posts/1
            print(f"  GET  /posts/1   c={c:<3} … ", end="", flush=True)
            out = run_wrk(f"http://127.0.0.1:{port}/posts/1", c)
            rec = parse_wrk_output(out, name, "get_post", c)
            results.append(rec)
            print(f"RPS={rec['requests_per_second']:8.1f}  avg={rec['avg_latency_ms']:7.2f}ms  "
                  f"p90={rec['p90_latency_ms']:7.2f}ms  p99={rec['p99_latency_ms']:7.2f}ms  err={rec['error_rate']}%")

            # POST /posts
            print(f"  POST /posts      c={c:<3} … ", end="", flush=True)
            out = run_wrk(
                f"http://127.0.0.1:{port}/posts",
                c,
                lua_script=str(SCRIPTS_DIR / "post.lua"),
            )
            rec = parse_wrk_output(out, name, "create_post", c)
            results.append(rec)
            print(f"RPS={rec['requests_per_second']:8.1f}  avg={rec['avg_latency_ms']:7.2f}ms  "
                  f"p90={rec['p90_latency_ms']:7.2f}ms  p99={rec['p99_latency_ms']:7.2f}ms  err={rec['error_rate']}%")

    finally:
        stop_server(proc)
        print(f"  {name} server stopped.")
        save_results(results)  # checkpoint after each framework


def save_results(results: list[dict]) -> None:
    json_path = RESULTS_DIR / "results.json"
    csv_path  = RESULTS_DIR / "results.csv"

    json_path.write_text(json.dumps(results, indent=2))

    if results:
        with open(csv_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=results[0].keys())
            writer.writeheader()
            writer.writerows(results)

    print(f"\nResults saved:")
    print(f"  JSON → {json_path}")
    print(f"  CSV  → {csv_path}")


def main() -> None:
    print(f"wrk benchmark — {DURATION}s per scenario, {THREADS} threads")
    print(f"Concurrency levels: {CONCURRENCY_LEVELS}")
    print(f"Python: {sys.version.split()[0]}  |  wrk: {WRK}")

    results: list[dict] = []

    for fw in FRAMEWORKS:
        benchmark_framework(fw, results)
        time.sleep(1)  # brief cooldown between frameworks

    save_results(results)
    print(f"\nTotal scenarios recorded: {len(results)}")


if __name__ == "__main__":
    main()
