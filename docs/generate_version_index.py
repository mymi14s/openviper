#!/usr/bin/env python3
"""Generate the root index.html listing all published doc versions."""

from __future__ import annotations

import os
import re
import sys


def generate_index(pages_dir: str) -> None:
    """Scan *pages_dir* for version subdirectories and write index.html."""
    entries: list[dict[str, str]] = []
    for name in sorted(os.listdir(pages_dir), reverse=True):
        full = os.path.join(pages_dir, name)
        if not os.path.isdir(full):
            continue
        if name == "latest":
            entries.insert(
                0,
                {
                    "version": "latest",
                    "label": "latest (main)",
                    "path": "latest/index.html",
                },
            )
        elif re.match(r"^\d+\.\d+\.\d+", name):
            entries.append(
                {
                    "version": name,
                    "label": name,
                    "path": f"{name}/index.html",
                }
            )

    versions_html = "\n".join(
        f'            <a href="{e["path"]}"'
        f"{' class="latest"' if e['version'] == 'latest' else ''}>"
        f"{e['label']}</a>"
        for e in entries
    )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <title>OpenViper Documentation</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont,
                "Segoe UI", Roboto, sans-serif;
            background: #1a1a2e; color: #e0e0e0;
            margin: 0; padding: 2rem;
        }}
        .container {{ max-width: 600px; margin: 4rem auto; text-align: center; }}
        h1 {{ font-size: 2rem; margin-bottom: 0.5rem; }}
        p {{ color: #a0a0b0; margin-bottom: 2rem; }}
        .versions {{ display: flex; flex-direction: column; gap: 0.75rem; align-items: center; }}
        .versions a {{
            display: block; padding: 0.75rem 2rem;
            background: #16213e; color: #e0e0e0;
            text-decoration: none; border-radius: 6px;
            border: 1px solid #0f3460;
            transition: background 0.2s; width: 220px;
        }}
        .versions a:hover {{ background: #0f3460; }}
        .versions a.latest {{ font-weight: bold; border-color: #e94560; }}
        .repo {{ margin-top: 2rem; color: #6c7293; font-size: 0.85rem; }}
        .repo a {{ color: #e94560; text-decoration: none; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>OpenViper Documentation</h1>
        <p>Select a version to view the docs.</p>
        <div class="versions">
{versions_html}
        </div>
        <div class="repo">
            <a href="https://github.com/mymi14s/openviper">GitHub Repository</a>
        </div>
    </div>
</body>
</html>
"""
    with open(os.path.join(pages_dir, "index.html"), "w") as f:
        f.write(html)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <pages_dir>", file=sys.stderr)
        sys.exit(1)
    generate_index(sys.argv[1])
