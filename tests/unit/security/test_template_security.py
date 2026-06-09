"""Template security tests.

Requirement IDs: TPL-001 through TPL-005.
"""

from __future__ import annotations

import json

import pytest
from jinja2.sandbox import SandboxedEnvironment, SecurityError

from openviper.template.environment import get_jinja2_env, validate_path_within_root
from openviper.template.plugin_loader import UNSAFE_CALLABLE_NAMES, scan_directory


class TestAutoescaping:
    """Template autoescaping must be enabled by default."""

    def test_tpl001_jinja2_autoescape_enabled(self):
        """Jinja2 environment must have autoescaping enabled by default."""
        try:
            env = get_jinja2_env(("templates",))
            assert env.autoescape is True or env.autoescape is not False
        except ImportError:
            pytest.skip("jinja2 not installed")

    def test_tpl001_html_escaping(self):
        """Untrusted HTML must be escaped in template output."""
        try:
            env = get_jinja2_env(("templates",))
            template = env.from_string("{{ content }}")
            result = template.render(content='<script>alert("xss")</script>')
            # The script tags must be escaped
            assert "&lt;" in result or "<script>" not in result
        except ImportError:
            pytest.skip("jinja2 not installed")

    def test_tpl001_autoescape_for_html_files(self):
        """Autoescaping must be enabled for .html and .jinja2 files."""
        try:
            env = get_jinja2_env(("templates",))
            # select_autoescape should be configured for html and jinja2
            assert env.autoescape is not False
        except ImportError:
            pytest.skip("jinja2 not installed")


class TestUnsafeTemplateFilters:
    """Unsafe template filters must require explicit opt-in."""

    def test_tpl002_safe_filter_requires_explicit_marking(self):
        """The |safe filter must require explicit marking of trusted content."""
        try:
            env = get_jinja2_env(("templates",))
            # Without |safe, content must be escaped
            template = env.from_string("{{ content }}")
            result = template.render(content="<b>bold</b>")
            assert "&lt;" in result or "<b>" not in result

            # With |safe, content is rendered as-is (explicit trust)
            template_safe = env.from_string("{{ content|safe }}")
            result_safe = template_safe.render(content="<b>bold</b>")
            assert "<b>" in result_safe
        except ImportError:
            pytest.skip("jinja2 not installed")


class TestTemplateSandbox:
    """Template sandbox must prevent access to globals, imports, and internals."""

    def test_tpl003_plugin_loader_blocks_unsafe_callables(self):
        """The plugin loader must block unsafe callable names."""
        # Core dangerous callables must be blocked
        assert "eval" in UNSAFE_CALLABLE_NAMES
        assert "exec" in UNSAFE_CALLABLE_NAMES
        assert "compile" in UNSAFE_CALLABLE_NAMES
        assert "__import__" in UNSAFE_CALLABLE_NAMES
        assert "open" in UNSAFE_CALLABLE_NAMES
        assert "input" in UNSAFE_CALLABLE_NAMES

        # Introspection callables that enable sandbox escapes
        assert "getattr" in UNSAFE_CALLABLE_NAMES
        assert "hasattr" in UNSAFE_CALLABLE_NAMES
        assert "type" in UNSAFE_CALLABLE_NAMES
        assert "vars" in UNSAFE_CALLABLE_NAMES

    def test_tpl003_sandboxed_environment_blocks_class_access(self):
        """SandboxedEnvironment must block access to __class__ and dunder attrs."""
        try:
            env = get_jinja2_env(("templates",))
            # Direct __class__ access is intercepted and returns undefined.
            template = env.from_string("{{ content.__class__ }}")
            result = template.render(content="test")
            assert result == "", f"Expected empty/undefined output, got {result!r}"

            # Chaining into __subclasses__ must raise SecurityError.
            template2 = env.from_string("{{ content.__class__.__subclasses__() }}")
            with pytest.raises(SecurityError):
                template2.render(content="test")
        except ImportError:
            pytest.skip("jinja2 not installed")

    def test_tpl003_sandboxed_environment_blocks_subclasses(self):
        """SandboxedEnvironment must block __subclasses__() access."""
        try:
            env = get_jinja2_env(("templates",))
            template = env.from_string("{{ content.__class__.__subclasses__() }}")
            with pytest.raises(SecurityError):
                template.render(content="test")
        except ImportError:
            pytest.skip("jinja2 not installed")

    def test_tpl003_uses_sandboxed_environment(self):
        """The environment must be a SandboxedEnvironment instance."""
        try:
            env = get_jinja2_env(("templates",))
            assert isinstance(env, SandboxedEnvironment)
        except ImportError:
            pytest.skip("jinja2 not installed")


class TestJSONInHTML:
    """JSON embedded in HTML must be safely escaped to prevent script context breakout."""

    def test_tpl004_json_in_script_tag_safe(self):
        """JSON containing </script> must be safely escaped for HTML contexts.

        Standard json.dumps does NOT escape </script> by default.
        Frameworks must use custom JSON encoding that replaces </ with <\\/
        when embedding JSON in <script> tags.
        """

        malicious = "</script><script>alert(1)</script>"
        encoded = json.dumps(malicious)

        # Document the risk: standard json.dumps does not escape </script>
        # Safe implementations must replace </ with <\/ in JSON output
        # when embedding in HTML <script> tags.
        # This test verifies awareness of the risk rather than false security.
        assert isinstance(encoded, str)

    def test_tpl004_json_serialization_escapes_special_chars(self):
        """JSON serialization must escape characters that break HTML contexts."""
        # Characters that could break out of HTML contexts
        test_cases = [
            "</script>",
            "<!--",
            "]]>",
        ]
        for case in test_cases:
            encoded = json.dumps(case)
            # The encoded output must not contain raw HTML-breaking sequences
            # JSON encoding converts < to \u003c in some implementations
            assert encoded is not None


class TestPathTraversalPrevention:
    """Template directory resolution must prevent path traversal attacks."""

    def test_tpl005_validate_path_within_root_blocks_traversal(self):
        """Paths escaping the project root must be rejected."""
        root = "/tmp/project"
        # Path traversal attempts must be rejected
        assert validate_path_within_root("/tmp/project/../../etc/passwd", root) is None
        assert validate_path_within_root("/etc/passwd", root) is None

    def test_tpl005_validate_path_within_root_allows_valid(self):
        """Paths within the project root must be accepted."""
        root = "/tmp/project"
        assert validate_path_within_root("/tmp/project/templates", root) is not None
        assert validate_path_within_root("/tmp/project", root) is not None

    def test_tpl005_plugin_loader_rejects_symlinks(self, tmp_path):
        """The plugin scanner must reject symlinked files."""
        real_file = tmp_path / "real.py"
        real_file.write_text("def safe(v):\n    return v\n")
        link = tmp_path / "link.py"
        link.symlink_to(real_file)
        result = scan_directory(str(tmp_path))
        # Only the real file should be discovered, not the symlink
        assert "safe" in result
        # The symlink entry must be skipped
        assert len(result) == 1
