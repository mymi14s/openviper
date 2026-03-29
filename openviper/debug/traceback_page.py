"""Rich HTML debug error page for OpenViper.

Renders a detailed, browser-friendly traceback page when ``DEBUG=True``.
This module must **never** be imported unconditionally in production paths;
it is imported lazily only when a 500-level error occurs in debug mode.
"""

from __future__ import annotations

import html
import linecache
import sys
import traceback
from typing import Any

_CONTEXT_LINES = 7

_CSS = """
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
body {
    font-family: "SFMono-Regular", "Menlo", "Monaco", "Consolas", monospace;
    font-size: 13px;
    background: #111827;
    color: #e5e7eb;
    line-height: 1.5;
}
a { color: #60a5fa; }

/* ── Header ─────────────────────────────────────────────────── */
.error-header {
    background: linear-gradient(135deg, #7f1d1d 0%, #991b1b 100%);
    padding: 24px 32px;
    border-bottom: 3px solid #6b1414;
    word-break: break-word;
}
.error-header .badge {
    display: inline-block;
    background: rgba(255,255,255,.15);
    color: #fecaca;
    font-size: 11px;
    font-weight: 600;
    letter-spacing: .08em;
    text-transform: uppercase;
    padding: 2px 8px;
    border-radius: 3px;
    margin-bottom: 10px;
}
.error-header .exc-type {
    font-size: 28px;
    font-weight: 700;
    color: #fff;
    letter-spacing: -0.5px;
}
.error-header .exc-msg {
    margin-top: 8px;
    font-size: 15px;
    color: #fca5a5;
    white-space: pre-wrap;
}
.error-header .debug-warning {
    margin-top: 14px;
    font-size: 11px;
    color: rgba(255,255,255,0.45);
    letter-spacing: .04em;
}

/* ── Layout ──────────────────────────────────────────────────── */
.container {
    max-width: 1100px;
    margin: 0 auto;
    padding: 24px 20px 48px;
}

/* ── Section ─────────────────────────────────────────────────── */
.section {
    background: #1f2937;
    border: 1px solid #374151;
    border-radius: 8px;
    margin: 20px 0;
    overflow: hidden;
}
.section-title {
    background: #111827;
    padding: 10px 16px;
    font-size: 11px;
    font-weight: 700;
    color: #9ca3af;
    text-transform: uppercase;
    letter-spacing: .1em;
    border-bottom: 1px solid #374151;
}

/* ── Traceback frames ────────────────────────────────────────── */
.traceback-intro {
    padding: 10px 16px;
    font-size: 12px;
    color: #6b7280;
    border-bottom: 1px solid #374151;
}
.frame {
    border-bottom: 1px solid #374151;
}
.frame:last-child { border-bottom: none; }

.frame-header {
    padding: 9px 16px;
    background: #1a2436;
    font-size: 12px;
    display: flex;
    flex-wrap: wrap;
    gap: 4px;
    align-items: baseline;
}
.frame-file { color: #7dd3fc; }
.frame-func { color: #fbbf24; font-weight: 600; }
.frame-lineno { color: #f87171; }
.frame-sep { color: #4b5563; margin: 0 2px; }

.frame-source {
    background: #0f172a;
    font-size: 12px;
    overflow-x: auto;
}
.src-line {
    display: flex;
    min-height: 20px;
}
.src-line:hover { background: #1e293b; }
.src-line.current {
    background: #3b1515;
    box-shadow: inset 3px 0 0 #ef4444;
}
.lineno {
    min-width: 52px;
    width: 52px;
    text-align: right;
    padding: 2px 10px 2px 6px;
    color: #4b5563;
    user-select: none;
    border-right: 1px solid #1e293b;
    flex-shrink: 0;
}
.src-line.current .lineno { color: #f87171; }
.code {
    padding: 2px 12px;
    white-space: pre;
    flex: 1;
    color: #cbd5e1;
    overflow: hidden;
}
.src-line.current .code { color: #fca5a5; }

/* ── Chain note ──────────────────────────────────────────────── */
.chain-note {
    padding: 12px 16px;
    background: #292524;
    border-bottom: 1px solid #374151;
    color: #fb923c;
    font-size: 12px;
}
.chain-note strong { color: #fdba74; }

/* ── Info table (request / env) ──────────────────────────────── */
.info-table {
    width: 100%;
    border-collapse: collapse;
}
.info-table td {
    padding: 7px 16px;
    border-bottom: 1px solid #1f2937;
    vertical-align: top;
    font-size: 12px;
}
.info-table tr:last-child td { border-bottom: none; }
.info-table td.key {
    color: #9ca3af;
    width: 220px;
    font-weight: 600;
}
.info-table td.val {
    color: #e2e8f0;
    word-break: break-all;
}
.subsection-title {
    padding: 8px 16px 4px;
    font-size: 11px;
    font-weight: 700;
    color: #6b7280;
    text-transform: uppercase;
    letter-spacing: .08em;
    border-bottom: 1px solid #374151;
    background: #1a2030;
}
.empty-note {
    padding: 8px 16px;
    font-size: 12px;
    color: #4b5563;
    font-style: italic;
}

/* ── Footer ──────────────────────────────────────────────────── */
.footer {
    text-align: center;
    color: #374151;
    padding: 32px 20px;
    font-size: 11px;
}
"""


def _esc(value: Any) -> str:
    """Escape a value for safe HTML embedding."""
    return html.escape(str(value))


def _get_source_context(
    filename: str,
    lineno: int,
    context: int = _CONTEXT_LINES,
) -> list[tuple[int, str, bool]]:
    """Return ``(lineno, source_line, is_current)`` tuples around *lineno*."""
    linecache.checkcache(filename)
    start = max(1, lineno - context)
    end = lineno + context + 1
    result: list[tuple[int, str, bool]] = []
    for n in range(start, end):
        line = linecache.getline(filename, n)
        if line:
            result.append((n, line.rstrip("\n\r"), n == lineno))
    return result


def _render_frame(frame: traceback.FrameSummary) -> str:
    """Render a single traceback frame as an HTML block."""
    filename = frame.filename or "<unknown>"
    lineno = frame.lineno or 0
    name = frame.name or "<unknown>"

    source_lines = _get_source_context(filename, lineno)

    source_html_parts: list[str] = []
    for n, line, is_current in source_lines:
        cls = 'src-line current" aria-current="true' if is_current else "src-line"
        source_html_parts.append(
            f'<div class="{cls}">'
            f'<span class="lineno">{_esc(n)}</span>'
            f'<span class="code">{_esc(line)}</span>'
            f"</div>"
        )
    source_html = "".join(source_html_parts)

    return (
        f'<div class="frame">'
        f'<div class="frame-header">'
        f'<span class="frame-file">{_esc(filename)}</span>'
        f'<span class="frame-sep">in</span>'
        f'<span class="frame-func">{_esc(name)}</span>'
        f'<span class="frame-sep">line</span>'
        f'<span class="frame-lineno">{_esc(lineno)}</span>'
        f"</div>"
        f'<div class="frame-source">{source_html}</div>'
        f"</div>"
    )


def _render_exception_chain(exc: BaseException) -> str:
    """Render any chained exception context as an HTML note."""
    cause = exc.__cause__
    context = exc.__context__
    if cause is not None:
        label = "The above exception was the direct cause of the following:"
        chain_type = _esc(type(cause).__name__)
        chain_msg = _esc(str(cause))
        return (
            f'<div class="chain-note">{_esc(label)} '
            f"<strong>{chain_type}: {chain_msg}</strong></div>"
        )
    if context is not None and not exc.__suppress_context__:
        label = "During handling of the above exception, another exception occurred:"
        chain_type = _esc(type(context).__name__)
        chain_msg = _esc(str(context))
        return (
            f'<div class="chain-note">{_esc(label)} '
            f"<strong>{chain_type}: {chain_msg}</strong></div>"
        )
    return ""


def _render_request_section(request: Any) -> str:
    """Render an HTML section with request metadata."""
    try:
        method = _esc(getattr(request, "method", "?"))
        path = _esc(getattr(request, "path", "?"))
    except Exception:
        return ""

    rows: list[str] = [
        f'<tr><td class="key">Method</td><td class="val">{method}</td></tr>',
        f'<tr><td class="key">Path</td><td class="val">{path}</td></tr>',
    ]

    query_rows: list[str] = []
    try:
        query_params = dict(request.query_params) if hasattr(request, "query_params") else {}
        for k, v in sorted(query_params.items()):
            query_rows.append(
                f'<tr><td class="key">{_esc(k)}</td><td class="val">{_esc(v)}</td></tr>'
            )
    except Exception:
        pass

    header_rows: list[str] = []
    try:
        headers = dict(request.headers) if hasattr(request, "headers") else {}
        for k, v in sorted(headers.items()):
            header_rows.append(
                f'<tr><td class="key">{_esc(k)}</td><td class="val">{_esc(v)}</td></tr>'
            )
    except Exception:
        pass

    query_html = '<div class="subsection-title">Query Parameters</div>' + (
        f'<table class="info-table">{"".join(query_rows)}</table>'
        if query_rows
        else '<p class="empty-note">No query parameters.</p>'
    )

    headers_html = '<div class="subsection-title">Headers</div>' + (
        f'<table class="info-table">{"".join(header_rows)}</table>'
        if header_rows
        else '<p class="empty-note">No headers.</p>'
    )

    return (
        '<div class="section">'
        '<div class="section-title">Request</div>'
        f'<table class="info-table">{"".join(rows)}</table>'
        f"{query_html}"
        f"{headers_html}"
        "</div>"
    )


def render_debug_page(exc: BaseException, request: Any | None = None) -> str:
    """Render a rich HTML debug page for an unhandled exception.

    This function is intentionally imported lazily and is only called when
    ``DEBUG=True`` and an unhandled exception occurs during request handling.

    Args:
        exc: The unhandled exception.
        request: Optional request object for additional context.

    Returns:
        A self-contained HTML string safe to send as an HTTP 500 response.
    """
    exc_class = type(exc)
    exc_module = exc_class.__module__
    exc_type_short = exc_class.__name__
    exc_type_full = (
        exc_type_short
        if not exc_module or exc_module == "builtins"
        else f"{exc_module}.{exc_type_short}"
    )
    exc_msg = str(exc)

    tb = exc.__traceback__
    summary = traceback.extract_tb(tb)
    frames_html = "".join(_render_frame(f) for f in summary)

    chain_html = _render_exception_chain(exc)
    request_html = _render_request_section(request) if request is not None else ""

    py_version = _esc(sys.version.split()[0])
    page_title = _esc(f"{exc_type_short}: {exc_msg[:120]}")
    exc_type_html = _esc(exc_type_full)
    exc_msg_html = _esc(exc_msg)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{page_title}</title>
  <style>{_CSS}</style>
</head>
<body>
  <div class="error-header">
    <div class="badge">Internal Server Error</div>
    <div class="exc-type">{exc_type_html}</div>
    <div class="exc-msg">{exc_msg_html}</div>
    <div class="debug-warning">
      This page is only visible in DEBUG mode &mdash; never expose it in production.
    </div>
  </div>

  <div class="container">
    <div class="section">
      <div class="section-title">Traceback</div>
      <div class="traceback-intro">Traceback (most recent call last):</div>
      {chain_html}
      {frames_html}
    </div>

    {request_html}

    <div class="footer">
      OpenViper &bull; Python {py_version} &bull; Debug mode &mdash; disable before deploying.
    </div>
  </div>
</body>
</html>"""
