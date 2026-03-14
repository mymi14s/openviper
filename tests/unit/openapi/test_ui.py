"""Unit tests for openviper.openapi.ui — Swagger and ReDoc HTML generators."""

from openviper.openapi.ui import REDOC_CDN, SWAGGER_UI_CDN, get_redoc_html, get_swagger_html


class TestSwaggerHTML:
    def test_contains_title(self):
        html = get_swagger_html("My API", "/openapi.json")
        assert "My API" in html

    def test_contains_openapi_url(self):
        html = get_swagger_html("API", "/api/openapi.json")
        assert "/api/openapi.json" in html

    def test_contains_swagger_ui_cdn(self):
        html = get_swagger_html("API", "/openapi.json")
        assert SWAGGER_UI_CDN in html

    def test_is_valid_html(self):
        html = get_swagger_html("Test", "/openapi.json")
        assert html.strip().startswith("<!DOCTYPE html>")
        assert "</html>" in html

    def test_contains_csrf_interceptor(self):
        html = get_swagger_html("API", "/openapi.json")
        assert "csrftoken" in html

    def test_xss_title_escaped(self):
        html = get_swagger_html("<script>alert(1)</script>", "/openapi.json")
        assert "<script>alert(1)</script>" not in html
        assert "&lt;script&gt;" in html

    def test_xss_url_escaped(self):
        html = get_swagger_html("API", '"></script><script>alert(1)</script>')
        assert "</script><script>" not in html


class TestRedocHTML:
    def test_contains_title(self):
        html = get_redoc_html("My API", "/openapi.json")
        assert "My API" in html

    def test_contains_openapi_url(self):
        html = get_redoc_html("API", "/api/openapi.json")
        assert "/api/openapi.json" in html

    def test_contains_redoc_cdn(self):
        html = get_redoc_html("API", "/openapi.json")
        assert REDOC_CDN in html

    def test_contains_redoc_tag(self):
        html = get_redoc_html("API", "/openapi.json")
        assert "<redoc" in html

    def test_is_valid_html(self):
        html = get_redoc_html("Test", "/openapi.json")
        assert html.strip().startswith("<!DOCTYPE html>")
        assert "</html>" in html

    def test_xss_title_escaped(self):
        html = get_redoc_html("<script>alert(1)</script>", "/openapi.json")
        assert "<script>alert(1)</script>" not in html
        assert "&lt;script&gt;" in html

    def test_xss_url_escaped(self):
        html = get_redoc_html("API", "'><script>alert(1)</script>")
        assert "<script>" not in html
