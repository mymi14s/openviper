#!/usr/bin/env python3.14
"""scripts/generate_report.py

Aggregate benchmark results, generate charts, and write a Markdown report.

Dependencies (install in any venv):
    pip install matplotlib pandas tabulate

Usage:
    cd benchmark_frameworks
    python3.14 scripts/generate_report.py
"""

from __future__ import annotations

import json
import platform
import subprocess
import sys
from datetime import datetime
from pathlib import Path

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.ticker as ticker
    HAS_MATPLOTLIB = True
except ImportError:
    HAS_MATPLOTLIB = False
    print("[WARN] matplotlib not installed – charts will be skipped")

try:
    import pandas as pd
    HAS_PANDAS = True
except ImportError:
    HAS_PANDAS = False
    print("[WARN] pandas not installed – table formatting degraded")

ROOT = Path(__file__).resolve().parent.parent
RESULTS_FILE = ROOT / "benchmarks" / "results" / "results.json"
REPORTS_DIR = ROOT / "reports"
CHARTS_DIR = REPORTS_DIR / "charts"
REPORT_FILE = REPORTS_DIR / "framework_performance_report.md"

FRAMEWORKS = ["OpenViper", "FastAPI", "Flask", "Django"]
CONCURRENCY_LEVELS = [10, 50, 100, 200]
FRAMEWORK_COLORS = {
    "OpenViper": "#2563eb",
    "FastAPI":   "#16a34a",
    "Flask":     "#d97706",
    "Django":    "#dc2626",
}


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_results() -> list[dict]:
    if not RESULTS_FILE.exists():
        print(f"[ERROR] Results file not found: {RESULTS_FILE}")
        print("        Run scripts/run_benchmarks.sh first.")
        sys.exit(1)
    data = json.loads(RESULTS_FILE.read_text())
    print(f"Loaded {len(data)} result rows from {RESULTS_FILE}")
    return data


def rows_for(data: list[dict], endpoint: str) -> list[dict]:
    return [r for r in data if r["endpoint"] == endpoint]


# ---------------------------------------------------------------------------
# Chart generation
# ---------------------------------------------------------------------------

def _setup_ax(ax: "plt.Axes", title: str, xlabel: str, ylabel: str) -> None:
    ax.set_title(title, fontsize=13, fontweight="bold", pad=12)
    ax.set_xlabel(xlabel, fontsize=10)
    ax.set_ylabel(ylabel, fontsize=10)
    ax.grid(axis="y", linestyle="--", alpha=0.4)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)


def chart_rps_vs_concurrency(data: list[dict]) -> str:
    """Line chart: Requests/sec vs concurrency for GET /posts/{id}."""
    CHARTS_DIR.mkdir(parents=True, exist_ok=True)
    path = CHARTS_DIR / "rps_vs_concurrency.png"

    fig, axes = plt.subplots(1, 2, figsize=(14, 5))
    for ax, endpoint, label in zip(
        axes,
        ["get_post", "create_post"],
        ["GET /posts/{id}", "POST /posts"],
    ):
        for fw in FRAMEWORKS:
            rows = sorted(
                [r for r in data if r["framework"] == fw and r["endpoint"] == endpoint],
                key=lambda r: r["concurrency"],
            )
            if not rows:
                continue
            xs = [r["concurrency"] for r in rows]
            ys = [r["requests_per_second"] for r in rows]
            ax.plot(xs, ys, marker="o", label=fw, color=FRAMEWORK_COLORS[fw], linewidth=2)
        _setup_ax(ax, f"Requests/sec — {label}", "Concurrency", "Req/sec")
        ax.legend(fontsize=9)

    fig.suptitle("Requests per Second vs Concurrency", fontsize=15, fontweight="bold")
    fig.tight_layout()
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  Chart saved: {path}")
    return str(path.relative_to(ROOT))


def chart_latency_vs_concurrency(data: list[dict]) -> str:
    """Line chart: avg/P95/P99 latency vs concurrency for GET."""
    path = CHARTS_DIR / "latency_vs_concurrency.png"
    rows_get = rows_for(data, "get_post")

    fig, axes = plt.subplots(1, 3, figsize=(16, 5), sharey=False)
    for ax, metric, label in zip(
        axes,
        ["avg_latency_ms", "p90_latency_ms", "p99_latency_ms"],
        ["Avg Latency (ms)", "P90 Latency (ms)", "P99 Latency (ms)"],
    ):
        for fw in FRAMEWORKS:
            rows = sorted(
                [r for r in rows_get if r["framework"] == fw],
                key=lambda r: r["concurrency"],
            )
            if not rows:
                continue
            xs = [r["concurrency"] for r in rows]
            ys = [r[metric] for r in rows]
            ax.plot(xs, ys, marker="s", label=fw, color=FRAMEWORK_COLORS[fw], linewidth=2)
        _setup_ax(ax, label, "Concurrency", "Latency (ms)")
        ax.legend(fontsize=9)

    fig.suptitle("Latency vs Concurrency — GET /posts/{id}", fontsize=15, fontweight="bold")
    fig.tight_layout()
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  Chart saved: {path}")
    return str(path.relative_to(ROOT))


def chart_framework_comparison_bar(data: list[dict]) -> str:
    """Bar chart: peak RPS per framework at concurrency=100."""
    path = CHARTS_DIR / "framework_comparison_bar.png"
    target_c = 100

    fig, axes = plt.subplots(1, 2, figsize=(12, 5))
    for ax, endpoint, label in zip(
        axes,
        ["get_post", "create_post"],
        ["GET /posts/{id}", "POST /posts"],
    ):
        fws, rps_vals = [], []
        for fw in FRAMEWORKS:
            match = [
                r for r in data
                if r["framework"] == fw
                and r["endpoint"] == endpoint
                and r["concurrency"] == target_c
            ]
            if match:
                fws.append(fw)
                rps_vals.append(match[0]["requests_per_second"])

        bars = ax.bar(
            fws, rps_vals,
            color=[FRAMEWORK_COLORS[f] for f in fws],
            edgecolor="white", linewidth=0.5,
        )
        ax.bar_label(bars, fmt="%.0f", padding=3, fontsize=9)
        _setup_ax(ax, f"Peak RPS at c={target_c} — {label}", "Framework", "Req/sec")
        ax.set_ylim(0, max(rps_vals) * 1.2 if rps_vals else 1)

    fig.suptitle("Framework Comparison — Requests per Second", fontsize=15, fontweight="bold")
    fig.tight_layout()
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  Chart saved: {path}")
    return str(path.relative_to(ROOT))


# ---------------------------------------------------------------------------
# Markdown table helpers
# ---------------------------------------------------------------------------

def _md_table(headers: list[str], rows: list[list]) -> str:
    col_widths = [
        max(len(str(h)), max((len(str(r[i])) for r in rows), default=0))
        for i, h in enumerate(headers)
    ]
    sep = "| " + " | ".join("-" * w for w in col_widths) + " |"
    header = "| " + " | ".join(str(h).ljust(col_widths[i]) for i, h in enumerate(headers)) + " |"
    lines = [header, sep]
    for row in rows:
        lines.append("| " + " | ".join(str(row[i]).ljust(col_widths[i]) for i in range(len(headers))) + " |")
    return "\n".join(lines)


def _performance_matrix_table(data: list[dict], endpoint: str) -> str:
    headers = [
        "Framework", "Concurrency", "Req/sec",
        "Avg (ms)", "P90 (ms)", "P99 (ms)", "Err %",
    ]
    rows_data = sorted(
        rows_for(data, endpoint),
        key=lambda r: (r["framework"], r["concurrency"]),
    )
    rows = [
        [
            r["framework"],
            r["concurrency"],
            f"{r['requests_per_second']:.2f}",
            f"{r['avg_latency_ms']:.3f}",
            f"{r['p90_latency_ms']:.3f}",
            f"{r['p99_latency_ms']:.3f}",
            f"{r['error_rate']:.4f}",
        ]
        for r in rows_data
    ]
    return _md_table(headers, rows)


# ---------------------------------------------------------------------------
# Hardware + Python info
# ---------------------------------------------------------------------------

def _hardware_info() -> str:
    python_version = sys.version.split()[0]
    try:
        if platform.system() == "Darwin":
            cpu = subprocess.check_output(["sysctl", "-n", "machdep.cpu.brand_string"], text=True).strip()
        else:
            cpu = subprocess.check_output(
                ["sh", "-c", "lscpu | grep 'Model name' | cut -d: -f2 | xargs"],
                text=True,
            ).strip()
    except Exception:
        cpu = platform.processor() or "unknown"
    return (
        f"- **OS**: {platform.system()} {platform.release()}\n"
        f"- **Python**: {python_version}\n"
        f"- **CPU**: {cpu}\n"
        f"- **Database**: SQLite (one DB per framework)\n"
        f"- **HTTP Benchmark Tool**: wrk (4 threads, 30s duration per scenario)\n"
    )


# ---------------------------------------------------------------------------
# Report assembly
# ---------------------------------------------------------------------------

def generate_report(data: list[dict], chart_paths: dict[str, str]) -> None:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

    # Best RPS at c=100 per framework (GET)
    def peak_rps(fw: str, endpoint: str = "get_post") -> float:
        match = [r for r in data if r["framework"] == fw and r["endpoint"] == endpoint and r["concurrency"] == 100]
        return match[0]["requests_per_second"] if match else 0.0

    fw_by_rps = sorted(FRAMEWORKS, key=lambda f: peak_rps(f), reverse=True)
    winner = fw_by_rps[0] if fw_by_rps else "N/A"

    sections: list[str] = []

    # --- Introduction ---
    sections.append(f"""\
# OpenViper Framework Performance Benchmark

*Generated: {now}*

## Introduction

This report compares the HTTP request-handling performance of four Python web
frameworks — **OpenViper**, **FastAPI**, **Flask**, and **Django** — using
identical blog API implementations backed by SQLite.

Each implementation exposes two endpoints:

| Endpoint | Description |
|----------|-------------|
| `POST /posts` | Create a blog post |
| `GET /posts/{{id}}` | Retrieve a blog post by ID |

Benchmarks were executed with **wrk** at concurrency levels
{", ".join(str(c) for c in CONCURRENCY_LEVELS)} over 30-second windows.
""")

    # --- Benchmark Setup ---
    sections.append("""\
## Benchmark Setup

### Framework Configurations

| Framework | Server | Workers | Mode |
|-----------|--------|---------|------|
| OpenViper | uvicorn | 4 | ASGI async |
| FastAPI   | uvicorn | 4 | ASGI async |
| Flask     | gunicorn | 4 | WSGI sync |
| Django    | gunicorn | 4 | WSGI sync |

### wrk Parameters

```
wrk -t4 -c<concurrency> -d30s [--lua post.lua] http://localhost:<port>/<path>
```
""")

    # --- Hardware Environment ---
    sections.append(f"""\
## Hardware Environment

{_hardware_info()}
""")

    # --- Performance Matrix ---
    sections.append(f"""\
## Performance Matrix

### GET /posts/{{id}}

{_performance_matrix_table(data, "get_post")}

### POST /posts

{_performance_matrix_table(data, "create_post")}
""")

    # --- Charts ---
    chart_section = "## Charts\n\n"
    for title, key in [
        ("Requests per Second vs Concurrency", "rps"),
        ("Latency vs Concurrency (GET)", "latency"),
        ("Framework Comparison — Peak RPS at Concurrency 100", "bar"),
    ]:
        path = chart_paths.get(key, "")
        if path:
            chart_section += f"### {title}\n\n![{title}]({path})\n\n"
        else:
            chart_section += f"### {title}\n\n*Chart not generated (matplotlib unavailable)*\n\n"
    sections.append(chart_section)

    # --- Analysis ---
    sections.append(f"""\
## Analysis

### Throughput

At concurrency 100 (GET /posts/{{id}}), the ranking by requests per second:

{chr(10).join(f'{i+1}. **{fw}** — {peak_rps(fw):.2f} req/sec' for i, fw in enumerate(fw_by_rps))}

### Latency

Async frameworks (OpenViper, FastAPI) benefit from non-blocking I/O, which
typically produces lower and more stable tail latencies compared to synchronous
WSGI frameworks (Flask, Django) under high concurrency.

### Error Rate

All frameworks should report 0% error rates under the tested load. A non-zero
error rate indicates resource exhaustion at the current worker count or SQLite
write contention.
""")

    # --- Conclusions ---
    sections.append(f"""\
## Conclusions

- **{winner}** achieved the highest throughput in the GET benchmark at c=100.
- Async ASGI frameworks outperform synchronous WSGI frameworks at higher
  concurrency due to non-blocking I/O capabilities.
- SQLite write contention is the primary bottleneck for POST endpoints across
  all frameworks; switching to PostgreSQL would yield higher write throughput.
- All frameworks are suitable for production use; framework choice should be
  driven by team familiarity, ecosystem fit, and workload characteristics in
  addition to raw throughput.
""")

    report_text = "\n".join(sections)
    REPORT_FILE.write_text(report_text)
    print(f"\nReport written to {REPORT_FILE}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    data = load_results()

    chart_paths: dict[str, str] = {}
    if HAS_MATPLOTLIB:
        print("\nGenerating charts …")
        chart_paths["rps"]     = chart_rps_vs_concurrency(data)
        chart_paths["latency"] = chart_latency_vs_concurrency(data)
        chart_paths["bar"]     = chart_framework_comparison_bar(data)

    print("\nAssembling report …")
    generate_report(data, chart_paths)


if __name__ == "__main__":
    main()
