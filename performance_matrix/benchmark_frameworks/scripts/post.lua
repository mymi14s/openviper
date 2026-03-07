-- wrk Lua script for POST /posts benchmark

wrk.method = "POST"
wrk.headers["Content-Type"] = "application/json"
wrk.body = '{"title":"Benchmark Post","content":"This is benchmark content for load testing purposes."}'
