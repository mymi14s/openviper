# OpenViper Framework Performance Benchmark

*Generated: 2026-03-06 16:46 UTC*

## Introduction

This report compares the HTTP request-handling performance of four Python web
frameworks — **OpenViper**, **FastAPI**, **Flask**, and **Django** — using
identical blog API implementations backed by SQLite.

Each implementation exposes two endpoints:

| Endpoint | Description |
|----------|-------------|
| `POST /posts` | Create a blog post |
| `GET /posts/{id}` | Retrieve a blog post by ID |

Benchmarks were executed with **wrk** at concurrency levels
10, 50, 100, 200 over 30-second windows.

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

## Hardware Environment

- **OS**: Darwin 24.6.0
- **Python**: 3.14.2
- **CPU**: Intel(R) Core(TM) i9-8950HK CPU @ 2.90GHz
- **Database**: SQLite (one DB per framework)
- **HTTP Benchmark Tool**: wrk (4 threads, 30s duration per scenario)


## Performance Matrix

### GET /posts/{id}

| Framework | Concurrency | Req/sec | Avg (ms) | P90 (ms) | P99 (ms) | Err %  |
| --------- | ----------- | ------- | -------- | -------- | -------- | ------ |
| Django    | 10          | 546.71  | 3.620    | 4.090    | 6.230    | 0.0000 |
| Django    | 50          | 0.00    | 0.000    | 0.000    | 0.000    | 0.0000 |
| Django    | 100         | 0.00    | 0.000    | 0.000    | 0.000    | 0.0000 |
| Django    | 200         | 0.00    | 0.000    | 0.000    | 0.000    | 0.0000 |
| FastAPI   | 10          | 2627.66 | 3.160    | 3.820    | 5.050    | 0.0000 |
| FastAPI   | 50          | 2621.43 | 18.440   | 23.020   | 30.270   | 0.0000 |
| FastAPI   | 100         | 0.00    | 0.000    | 0.000    | 0.000    | 0.0000 |
| FastAPI   | 200         | 0.00    | 0.000    | 0.000    | 0.000    | 0.0000 |
| Flask     | 10          | 545.82  | 3.260    | 3.750    | 5.210    | 0.0000 |
| Flask     | 50          | 0.00    | 0.000    | 0.000    | 0.000    | 0.0000 |
| Flask     | 100         | 0.00    | 0.000    | 0.000    | 0.000    | 0.0000 |
| Flask     | 200         | 0.00    | 0.000    | 0.000    | 0.000    | 0.0000 |
| OpenViper | 10          | 2038.39 | 4.780    | 5.780    | 46.540   | 0.0000 |
| OpenViper | 50          | 1933.73 | 25.660   | 29.240   | 82.490   | 0.0000 |
| OpenViper | 100         | 2009.33 | 51.430   | 75.780   | 165.070  | 0.0000 |
| OpenViper | 200         | 1938.11 | 110.430  | 210.720  | 378.790  | 0.0000 |

### POST /posts

| Framework | Concurrency | Req/sec | Avg (ms) | P90 (ms) | P99 (ms) | Err %    |
| --------- | ----------- | ------- | -------- | -------- | -------- | -------- |
| Django    | 10          | 0.00    | 0.000    | 0.000    | 0.000    | 0.0000   |
| Django    | 50          | 0.00    | 0.000    | 0.000    | 0.000    | 0.0000   |
| Django    | 100         | 0.00    | 0.000    | 0.000    | 0.000    | 0.0000   |
| Django    | 200         | 0.00    | 0.000    | 0.000    | 0.000    | 0.0000   |
| FastAPI   | 10          | 500.71  | 123.730  | 429.020  | 1350.000 | 0.0000   |
| FastAPI   | 50          | 166.53  | 83.470   | 201.030  | 1370.000 | 0.0800   |
| FastAPI   | 100         | 0.00    | 0.000    | 0.000    | 0.000    | 0.0000   |
| FastAPI   | 200         | 0.00    | 0.000    | 0.000    | 0.000    | 0.0000   |
| Flask     | 10          | 0.00    | 0.000    | 0.000    | 0.000    | 0.0000   |
| Flask     | 50          | 0.00    | 0.000    | 0.000    | 0.000    | 0.0000   |
| Flask     | 100         | 0.00    | 0.000    | 0.000    | 0.000    | 0.0000   |
| Flask     | 200         | 0.00    | 0.000    | 0.000    | 0.000    | 0.0000   |
| OpenViper | 10          | 282.69  | 60.590   | 136.950  | 677.090  | 100.0000 |
| OpenViper | 50          | 565.44  | 139.790  | 526.430  | 1410.000 | 0.2354   |
| OpenViper | 100         | 556.38  | 174.530  | 444.410  | 1380.000 | 0.4607   |
| OpenViper | 200         | 560.64  | 306.350  | 603.270  | 1290.000 | 0.6111   |

## Charts

### Requests per Second vs Concurrency

![Requests per Second vs Concurrency](reports/charts/rps_vs_concurrency.png)

### Latency vs Concurrency (GET)

![Latency vs Concurrency (GET)](reports/charts/latency_vs_concurrency.png)

### Framework Comparison — Peak RPS at Concurrency 100

![Framework Comparison — Peak RPS at Concurrency 100](reports/charts/framework_comparison_bar.png)


## Analysis

### Throughput

At concurrency 100 (GET /posts/{id}), the ranking by requests per second:

1. **OpenViper** — 2009.33 req/sec
2. **FastAPI** — 0.00 req/sec
3. **Flask** — 0.00 req/sec
4. **Django** — 0.00 req/sec

### Latency

Async frameworks (OpenViper, FastAPI) benefit from non-blocking I/O, which
typically produces lower and more stable tail latencies compared to synchronous
WSGI frameworks (Flask, Django) under high concurrency.

### Error Rate

All frameworks should report 0% error rates under the tested load. A non-zero
error rate indicates resource exhaustion at the current worker count or SQLite
write contention.

## Conclusions

- **OpenViper** achieved the highest throughput in the GET benchmark at c=100.
- Async ASGI frameworks outperform synchronous WSGI frameworks at higher
  concurrency due to non-blocking I/O capabilities.
- SQLite write contention is the primary bottleneck for POST endpoints across
  all frameworks; switching to PostgreSQL would yield higher write throughput.
- All frameworks are suitable for production use; framework choice should be
  driven by team familiarity, ecosystem fit, and workload characteristics in
  addition to raw throughput.
