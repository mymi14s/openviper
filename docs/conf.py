# Configuration file for the Sphinx documentation builder.
#
# OpenViper Documentation
# https://www.sphinx-doc.org/en/master/usage/configuration.html

import datetime
import os
import sys
import tomllib
from pathlib import Path

# Add the project root to sys.path so autodoc can import openviper modules.
sys.path.insert(0, os.path.abspath("../.."))

# Read version from pyproject.toml — single source of truth.
_pyproject = Path(__file__).resolve().parent.parent / "pyproject.toml"
with _pyproject.open("rb") as _f:
    _meta = tomllib.load(_f)
_project_version: str = _meta["project"]["version"]

# -- Project information -----------------------------------------------------

project = "OpenViper"
copyright = f"{datetime.datetime.now(tz=datetime.UTC).year}, OpenViper Contributors"  # noqa: A001
author = "E.A"
release = _project_version
version = _project_version

# -- General configuration ---------------------------------------------------

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.viewcode",
    "sphinx.ext.napoleon",
    "sphinx.ext.intersphinx",
    "sphinx.ext.todo",
    "sphinx.ext.coverage",
    "sphinx.ext.githubpages",
]

templates_path = []
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store", "_templates"]

# autodoc settings
autodoc_member_order = "bysource"
autodoc_typehints = "description"
autodoc_default_options = {
    "members": True,
    "undoc-members": True,
    "show-inheritance": True,
    "inherited-members": False,
}

# Suppress duplicate cross-reference and highlight warnings from source docstrings
suppress_warnings = [
    "ref.python",
    "misc.highlighting_failure",
]

# Napoleon settings (Google/NumPy-style docstrings)
napoleon_google_docstring = True
napoleon_numpy_docstring = False
napoleon_include_init_with_doc = True
napoleon_include_private_with_doc = False
napoleon_include_special_with_doc = True
napoleon_use_admonition_for_examples = True

# Intersphinx mapping
intersphinx_mapping = {
    "python": ("https://docs.python.org/3", None),
    "pydantic": ("https://docs.pydantic.dev/latest", None),
    "sqlalchemy": ("https://docs.sqlalchemy.org/en/20", None),
}

# -- Options for HTML output -------------------------------------------------

html_theme = "sphinx_rtd_theme"
html_static_path = ["_static"]

html_theme_options = {
    "logo_only": False,
    "prev_next_buttons_location": "bottom",
    "style_external_links": False,
    "style_nav_header_background": "#1a1a2e",
    "collapse_navigation": False,
    "sticky_navigation": True,
    "navigation_depth": 4,
    "includehidden": True,
    "titles_only": False,
}

html_context = {
    "display_github": True,
    "github_user": "openviper",
    "github_repo": "openviper",
    "github_version": "main",
    "conf_py_path": "/docs",
}

# -- Options for todo extension ----------------------------------------------
todo_include_todos = True

# -- Pygments syntax highlighting --------------------------------------------
pygments_style = "monokai"
highlight_language = "python3"
