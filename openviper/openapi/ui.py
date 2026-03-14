"""Swagger UI and ReDoc HTML generators."""

from __future__ import annotations

import html as _html

SWAGGER_UI_CDN = "https://cdn.jsdelivr.net/npm/swagger-ui-dist@5"
REDOC_CDN = "https://cdn.jsdelivr.net/npm/redoc@latest/bundles/redoc.standalone.js"


def get_swagger_html(title: str, openapi_url: str) -> str:
    """Generate the Swagger UI HTML page.

    Args:
        title: API title shown in the browser tab.
        openapi_url: URL of the OpenAPI JSON schema.

    Returns:
        Full HTML string for the Swagger UI page.
    """
    safe_title = _html.escape(title)
    safe_url = _html.escape(openapi_url)
    return f"""<!DOCTYPE html>
<html>
<head>
  <title>{safe_title} - Swagger UI</title>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <link rel="stylesheet" type="text/css" href="{SWAGGER_UI_CDN}/swagger-ui.css" >
  <style>
    html {{ box-sizing: border-box; overflow: -moz-scrollbars-vertical; overflow-y: scroll; }}
    *, *:before, *:after {{ box-sizing: inherit; }}
    body {{ margin: 0; background: #fafafa; }}
    .topbar {{ display: none; }}
  </style>
</head>
<body>
<div id="swagger-ui"></div>
<script src="{SWAGGER_UI_CDN}/swagger-ui-bundle.js"> </script>
<script src="{SWAGGER_UI_CDN}/swagger-ui-standalone-preset.js"> </script>
<script>
  window.onload = function() {{
    var ui = SwaggerUIBundle({{
      url: "{safe_url}",
      dom_id: '#swagger-ui',
      deepLinking: true,
      presets: [
        SwaggerUIBundle.presets.apis,
        SwaggerUIStandalonePreset
      ],
      plugins: [SwaggerUIBundle.plugins.DownloadUrl],
      layout: "StandaloneLayout",
      tryItOutEnabled: true,
      requestInterceptor: function(request) {{
        var csrfToken = document.cookie.split(';').find(c => c.trim().startsWith('csrftoken='));
        if (csrfToken) {{
          request.headers['X-CSRFToken'] = decodeURIComponent(csrfToken.split('=')[1].trim());
        }}
        return request;
      }}
    }})
    window.ui = ui
  }}
</script>
</body>
</html>"""


def get_redoc_html(title: str, openapi_url: str) -> str:
    """Generate the ReDoc HTML page.

    Args:
        title: API title shown in the browser tab.
        openapi_url: URL of the OpenAPI JSON schema.

    Returns:
        Full HTML string for the ReDoc page.
    """
    safe_title = _html.escape(title)
    safe_url = _html.escape(openapi_url)
    return f"""<!DOCTYPE html>
<html>
  <head>
    <title>{safe_title} - ReDoc</title>
    <meta charset="utf-8"/>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <link
      href="https://fonts.googleapis.com/css?family=Montserrat:300,400,700|Roboto:300,400,700"
      rel="stylesheet"
    >
    <style>
      body {{
        margin: 0;
        padding: 0;
      }}
    </style>
  </head>
  <body>
    <redoc spec-url='{safe_url}'></redoc>
    <script src="{REDOC_CDN}"> </script>
  </body>
</html>"""
