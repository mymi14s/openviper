"""Debug endpoint to check cookie behavior."""

from html import escape
from typing import TYPE_CHECKING

from openviper.http.response import HTMLResponse, Response

if TYPE_CHECKING:
    from openviper.http.request import Request


async def test_cookie_page(request: Request) -> Response:
    """Test page to debug cookie behavior."""
    received_cookies = request.cookies
    session_cookie = received_cookies.get("sessionid", "NOT FOUND")
    escaped_cookies = escape(str(received_cookies))
    escaped_session_cookie = escape(str(session_cookie))
    escaped_cookies_repr = escape(repr(received_cookies))
    cookie_class = "success" if session_cookie != "NOT FOUND" else "error"

    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Cookie Debug</title>
        <style>
            body {{ font-family: monospace; padding: 20px; }}
            .success {{ color: green; }}
            .error {{ color: red; }}
            pre {{ background: #f4f4f4; padding: 10px; }}
        </style>
    </head>
    <body>
        <h1>Cookie Debug Page</h1>

        <h2>Cookies Received by Server:</h2>
        <pre>{escaped_cookies}</pre>

        <h2>sessionid Cookie:</h2>
        <pre class="{cookie_class}">{escaped_session_cookie}</pre>

        <h2>Browser Cookies (JavaScript):</h2>
        <pre id="js-cookies"></pre>

        <h2>Actions:</h2>
        <button onclick="checkCookies()">Refresh Cookie List</button>
        <button onclick="window.location.href='/login'">Go to Login</button>
        <button onclick="window.location.href='/dashboard'">Go to Dashboard</button>

        <script>
            function checkCookies() {{
                document.getElementById('js-cookies').textContent =
                    document.cookie || 'No cookies found';
            }}
            checkCookies();

            console.log('document.cookie:', document.cookie);
            console.log('Server received:', {escaped_cookies_repr!r});
        </script>
    </body>
    </html>
    """

    return HTMLResponse(html)
