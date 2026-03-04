"""Landing page HTML template for OpenViper's default debug page."""

from __future__ import annotations

LANDING_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>OpenViper — Welcome</title>
    <style>
        :root {
            --primary: #6c5ce7;
            --primary-light: #a29bfe;
            --accent: #00cec9;
            --bg-dark: #0a0a23;
            --bg-card: rgba(255, 255, 255, 0.06);
            --text: #dfe6e9;
            --text-muted: #b2bec3;
            --border: rgba(255, 255, 255, 0.08);
            --success: #00b894;
            --radius: 16px;
        }
        *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
                         "Helvetica Neue", Arial, sans-serif;
            background: linear-gradient(135deg, var(--bg-dark) 0%, #1e1e3f 50%, #2d1b69 100%);
            color: var(--text);
            min-height: 100vh;
            display: flex;
            flex-direction: column;
            align-items: center;
            overflow-x: hidden;
        }
        .hero {
            text-align: center;
            padding: 6rem 2rem 3rem;
            max-width: 720px;
        }
        .hero h1 {
            font-size: 3.5rem;
            font-weight: 800;
            background: linear-gradient(135deg, var(--primary-light), var(--accent));
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
            margin-bottom: 0.5rem;
            letter-spacing: -1px;
        }
        .hero .version {
            font-size: 0.9rem;
            color: var(--text-muted);
            margin-bottom: 1.5rem;
        }
        .hero p {
            font-size: 1.2rem;
            color: var(--text-muted);
            line-height: 1.7;
        }
        .badge {
            display: inline-block;
            background: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: 24px;
            padding: 0.35rem 1rem;
            font-size: 0.8rem;
            color: var(--accent);
            margin-top: 1.5rem;
            backdrop-filter: blur(10px);
        }
        .features {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
            gap: 1.5rem;
            max-width: 960px;
            width: 100%;
            padding: 0 2rem 3rem;
        }
        .card {
            background: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: var(--radius);
            padding: 2rem;
            backdrop-filter: blur(12px);
            transition: transform 0.2s ease, border-color 0.2s ease;
        }
        .card:hover {
            transform: translateY(-4px);
            border-color: var(--primary-light);
        }
        .card .icon { font-size: 2rem; margin-bottom: 0.75rem; }
        .card h3 {
            font-size: 1.1rem;
            font-weight: 700;
            margin-bottom: 0.5rem;
            color: var(--text);
        }
        .card p {
            font-size: 0.9rem;
            color: var(--text-muted);
            line-height: 1.6;
        }
        .quickstart {
            max-width: 640px;
            width: 100%;
            padding: 0 2rem 4rem;
        }
        .quickstart h2 {
            font-size: 1.5rem;
            font-weight: 700;
            margin-bottom: 1rem;
            text-align: center;
        }
        .code-block {
            background: rgba(0, 0, 0, 0.5);
            border: 1px solid var(--border);
            border-radius: var(--radius);
            padding: 1.5rem;
            overflow-x: auto;
            font-family: "SF Mono", "Fira Code", "JetBrains Mono", monospace;
            font-size: 0.85rem;
            line-height: 1.8;
            color: var(--text);
        }
        .code-block .comment { color: #636e72; }
        .code-block .kw { color: var(--primary-light); }
        .code-block .fn { color: var(--accent); }
        .code-block .str { color: #ffeaa7; }
        .code-block .dec { color: #fd79a8; }
        footer {
            text-align: center;
            padding: 2rem;
            color: var(--text-muted);
            font-size: 0.8rem;
            border-top: 1px solid var(--border);
            width: 100%;
            max-width: 960px;
        }
        footer a {
            color: var(--primary-light);
            text-decoration: none;
        }
        footer a:hover { text-decoration: underline; }
        @media (max-width: 600px) {
            .hero h1 { font-size: 2.5rem; }
            .features { grid-template-columns: 1fr; }
        }
    </style>
</head>
<body>
    <div class="hero">
        <h1>&#x2764;&#xfe0f; OpenViper</h1>
        <div class="version">v{version}</div>
        <p>
            A production-ready, high-performance, async-first Python web framework.
        </p>
        <span class="badge">&#x1f6e1;&#xfe0f; DEBUG mode &mdash; this page is only visible in development</span>
    </div>

    <div class="features">
        <div class="card">
            <div class="icon">&#x26a1;</div>
            <h3>Async-First ASGI</h3>
            <p>Built on native async/await with full ASGI support.
               Zero-copy request processing for maximum throughput.</p>
        </div>
        <div class="card">
            <div class="icon">&#x1f3af;</div>
            <h3>Type-Safe Routing</h3>
            <p>Decorator-based routes with automatic path parameter
               extraction and response coercion.</p>
        </div>
        <div class="card">
            <div class="icon">&#x1f4e6;</div>
            <h3>Batteries Included</h3>
            <p>ORM, authentication, middleware, serializers, static files,
               background tasks, and OpenAPI docs out of the box.</p>
        </div>
        <div class="card">
            <div class="icon">&#x1f916;</div>
            <h3>AI Integration</h3>
            <p>First-class AI provider registry supporting OpenAI, Anthropic,
               Gemini, Grok, and Ollama.</p>
        </div>
        <div class="card">
            <div class="icon">&#x1f6e0;&#xfe0f;</div>
            <h3>Developer Experience</h3>
            <p>Powerful CLI, auto-reload, rich error pages, Swagger &amp; ReDoc
               API documentation.</p>
        </div>
        <div class="card">
            <div class="icon">&#x1f512;</div>
            <h3>Security Built-In</h3>
            <p>CSRF protection, JWT auth, password hashing (Argon2/bcrypt),
               CORS, and rate limiting middleware.</p>
        </div>
    </div>

    <div class="quickstart">
        <h2>Quick Start</h2>
        <div class="code-block">
<span class="comment"># Create a new project</span><br>
$ openviper create-project mysite<br>
$ <span class="kw">cd</span> mysite<br>
<span class="comment"># Run the development server</span><br>
$ python viperctl.py runserver<br>
        </div>
    </div>

    <footer>
        OpenViper Framework &mdash;
        <a href="https://github.com/openviper-project/openviper">GitHub</a> &middot;
        <a href="/open-api/docs">API Docs</a> &middot;
        <a href="/open-api/redoc">ReDoc</a>
    </footer>
</body>
</html>
"""
