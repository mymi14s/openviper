"""Debug endpoint to check cookie behavior."""
from openviper.http.response import HTMLResponse, Response
from openviper.http.request import Request


async def test_cookie_page(request: Request) -> Response:
    """Test page to debug cookie behavior."""
    
    # Check what cookies browser sent
    received_cookies = request.cookies
    
    # Check sessionid specifically
    session_cookie = received_cookies.get('sessionid', 'NOT FOUND')
    
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
        <pre>{received_cookies}</pre>
        
        <h2>sessionid Cookie:</h2>
        <pre class="{'success' if session_cookie != 'NOT FOUND' else 'error'}">{session_cookie}</pre>
        
        <h2>Browser Cookies (JavaScript):</h2>
        <pre id="js-cookies"></pre>
        
        <h2>Actions:</h2>
        <button onclick="checkCookies()">Refresh Cookie List</button>
        <button onclick="window.location.href='/login'">Go to Login</button>
        <button onclick="window.location.href='/dashboard'">Go to Dashboard</button>
        
        <script>
            function checkCookies() {{
                document.getElementById('js-cookies').textContent = document.cookie || 'No cookies found';
            }}
            checkCookies();
            
            // Log to console too
            console.log('document.cookie:', document.cookie);
            console.log('Server received:', {repr(received_cookies)});
        </script>
    </body>
    </html>
    """
    
    return HTMLResponse(html)
