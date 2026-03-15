"""Template and Markdown rendering helpers for email delivery."""

from __future__ import annotations

import html
from pathlib import Path
from typing import Any, cast

try:
    import markdown as markdown_lib
except ImportError:  # pragma: no cover - runtime dependency in requirements.txt
    markdown_lib = None

from openviper.conf import settings
from openviper.http.response import _compute_template_search_paths
from openviper.template.environment import get_jinja2_env


def render_template_content(
    template: str,
    context: dict[str, Any] | None = None,
    template_dir: str | Path = "templates",
) -> tuple[str | None, str | None]:
    """Render a template and return ``(text, html)`` content."""
    if ".." in template or template.startswith("/") or template.startswith("\\"):
        raise ValueError(f"Invalid template name: {template!r}")

    base_dir = template_dir
    if template_dir == "templates":
        base_dir = getattr(settings, "TEMPLATES_DIR", "templates")

    installed_apps = tuple(getattr(settings, "INSTALLED_APPS", ()))
    search_paths = _compute_template_search_paths(str(base_dir), installed_apps)
    env = get_jinja2_env(search_paths)
    rendered = cast("str", env.get_template(template).render(**(context or {})))

    suffixes = {suffix.lower() for suffix in Path(template).suffixes}
    if {".md", ".markdown"} & suffixes:
        return rendered, render_markdown(rendered)
    if {".html", ".htm"} & suffixes:
        return None, rendered
    return rendered, None


def render_markdown(markdown_text: str) -> str:
    """Convert Markdown to HTML using Markdown if installed, else a small fallback."""
    if markdown_lib is not None:
        return cast(
            "str",
            markdown_lib.markdown(markdown_text, extensions=["extra", "sane_lists"]),
        )

    lines = [line.rstrip() for line in markdown_text.splitlines()]
    rendered: list[str] = []
    for line in lines:
        if not line:
            continue
        if line.startswith("# "):
            rendered.append(f"<h1>{html.escape(line[2:])}</h1>")
            continue
        if line.startswith("## "):
            rendered.append(f"<h2>{html.escape(line[3:])}</h2>")
            continue
        rendered.append(f"<p>{html.escape(line)}</p>")
    return "\n".join(rendered)
