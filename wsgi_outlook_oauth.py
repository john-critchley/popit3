#!/usr/bin/env python3
"""
WSGI OAuth handler for Outlook token refresh using device flow (same as get_pop_refresh_token.py).

Device flow doesn't require redirect URI registration:
- No pre-registered callback needed
- User visits Microsoft's device login site
- Simple, seamless web interface to the device flow process

Usage in Apache:
    WSGIScriptAlias /authorize-outlook /path/to/wsgi_outlook_oauth.py

Environment variables (or defaults):
    OUTLOOK_CLIENT_ID  — Azure app client ID (default: app from get_pop_refresh_token.py)
    WEBDAV_ROOT        — webdav filesystem root (default: /var/www/webdav)
"""

import os
import sys
import json
import re
import time
import hashlib
import urllib.parse
import urllib.request
from typing import Optional, Tuple, Dict, Any
import logging
import logging.handlers

# Logging — file + stderr (stderr → Apache error log)
_log_handler = logging.handlers.RotatingFileHandler(
    '/tmp/wsgi_outlook_oauth.log', maxBytes=1_000_000, backupCount=3
)
_log_handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))

logger = logging.getLogger('wsgi_outlook_oauth')
logger.setLevel(logging.INFO)
if not logger.handlers:
    logger.addHandler(_log_handler)
    logger.addHandler(logging.StreamHandler())

# Try to import msal (same as script)
try:
    import msal
except ImportError:
    logger.error("ERROR: msal not installed. Run: pip install msal")
    raise

# Configuration (same as get_pop_refresh_token.py)
CLIENT_ID = os.environ.get('OUTLOOK_CLIENT_ID', '60da67f7-5fde-4e85-baf3-ab28d0c8e034')
AUTHORITY = 'https://login.microsoftonline.com/consumers'
TOKEN_ENDPOINT = 'https://login.microsoftonline.com/consumers/oauth2/v2.0/token'
SCOPES = ['https://outlook.office.com/POP.AccessAsUser.All']
SCOPE = SCOPES[0]  # used in netrc hint text
WEBDAV_BASE = '/var/www/webdav/outlook_tokens'
FLOW_STORE = '/tmp/outlook_wsgi_flows'


class TokenStore:
    """Store tokens in webdav-accessible location."""
    
    @staticmethod
    def _safe_filename(email: str) -> str:
        """Convert email to safe filename."""
        return email.replace('@', '_at_').replace('.', '_')
    
    @staticmethod
    def save_token(user_email: str, token_data: Dict[str, Any]) -> str:
        """Save token to webdav. Returns path."""
        os.makedirs(WEBDAV_BASE, mode=0o755, exist_ok=True)
        filename = TokenStore._safe_filename(user_email)
        filepath = os.path.join(WEBDAV_BASE, f'{filename}.json')
        
        # Add metadata
        token_data['user_email'] = user_email
        token_data['saved_at'] = time.time()
        
        with open(filepath, 'w') as f:
            json.dump(token_data, f, indent=2)
        
        os.chmod(filepath, 0o644)
        logger.info(f"Saved token for {user_email} to {filepath}")
        return filepath
    
    @staticmethod
    def get_token(user_email: str) -> Optional[Dict[str, Any]]:
        """Retrieve stored token."""
        filename = TokenStore._safe_filename(user_email)
        filepath = os.path.join(WEBDAV_BASE, f'{filename}.json')
        
        if os.path.exists(filepath):
            with open(filepath, 'r') as f:
                return json.load(f)
        return None
    
    @staticmethod
    def list_tokens() -> list:
        """List all stored tokens."""
        if not os.path.exists(WEBDAV_BASE):
            return []
        tokens = []
        for filename in os.listdir(WEBDAV_BASE):
            if filename.endswith('.json'):
                filepath = os.path.join(WEBDAV_BASE, filename)
                try:
                    with open(filepath, 'r') as f:
                        data = json.load(f)
                    tokens.append({
                        'user_email': data.get('user_email'),
                        'expires_in': data.get('expires_in'),
                        'saved_at': data.get('saved_at')
                    })
                except Exception as e:
                    logger.error(f"Error reading {filepath}: {e}")
        return tokens


def acquire_token_with_device_flow(user_email: str) -> Tuple[Optional[str], Dict[str, Any]]:
    """
    Initiate device flow and persist flow data to disk for cross-process polling.
    Returns: (flow_id, flow_data)
    """
    try:
        app = msal.PublicClientApplication(CLIENT_ID, authority=AUTHORITY)
        flow = app.initiate_device_flow(scopes=SCOPES)
        
        if "user_code" not in flow:
            error_msg = f"Failed to initiate device flow: {flow.get('error_description', str(flow))}"
            logger.error(error_msg)
            return None, {"error": error_msg}
        
        # Persist to disk so any worker process can poll it
        os.makedirs(FLOW_STORE, mode=0o700, exist_ok=True)
        flow_id = flow.get('device_code')
        # Hash the device_code (JWT, too long for a filename)
        flow_key = hashlib.sha256(flow_id.encode()).hexdigest()[:16]
        state = {
            'flow': flow,
            'user_email': user_email,
            'initiated_at': time.time()
        }
        with open(os.path.join(FLOW_STORE, f'{flow_key}.json'), 'w') as f:
            json.dump(state, f)
        
        logger.info(f"Device flow initiated for {user_email}")
        return flow_key, flow
        
    except Exception as e:
        error_msg = f"Error initiating device flow: {e}"
        logger.error(error_msg)
        return None, {"error": error_msg}


def poll_device_flow_completion(flow_id: str) -> Optional[Dict[str, Any]]:
    """
    Make a single non-blocking poll to Microsoft's token endpoint.
    Returns: token result if complete, None if still pending, dict with 'error' key on failure.
    """
    flow_file = os.path.join(FLOW_STORE, f'{flow_id}.json')
    if not os.path.exists(flow_file):
        logger.error(f"Unknown flow_id: {flow_id}")
        return {"error": "Unknown or expired flow"}
    
    with open(flow_file) as f:
        state = json.load(f)
    
    flow = state['flow']
    user_email = state['user_email']
    
    # Single-shot POST to token endpoint (no blocking loop)
    try:
        post_data = urllib.parse.urlencode({
            'grant_type': 'urn:ietf:params:oauth:grant-type:device_code',
            'client_id': CLIENT_ID,
            'device_code': flow['device_code'],
        }).encode('utf-8')
        req = urllib.request.Request(TOKEN_ENDPOINT, data=post_data, method='POST')
        req.add_header('Content-Type', 'application/x-www-form-urlencoded')
        
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        result = json.loads(e.read().decode('utf-8'))
    except Exception as e:
        return {"error": str(e)}
    
    if result.get('error') == 'authorization_pending':
        return None  # Still waiting
    
    if result.get('error') == 'slow_down':
        return None  # Slow down, still waiting
    
    if 'access_token' in result:
        # Success — clean up flow file and save token
        try:
            os.remove(flow_file)
        except OSError:
            pass
        result['user_email'] = user_email
        TokenStore.save_token(user_email, result)
        logger.info(f"Device flow completed for {user_email}")
        return result
    
    # Some other error
    error_msg = result.get('error_description', result.get('error', str(result)))
    logger.error(f"Device flow error: {error_msg}")
    try:
        os.remove(flow_file)
    except OSError:
        pass
    return {"error": error_msg}


def format_netrc_entry(refresh_token: str, user_email: str) -> str:
    """Format token as .netrc entry (same as script)."""
    return f"""machine outlook.office365.com
  login {user_email}
  account MSAL:{CLIENT_ID}
  password {refresh_token}"""


def application(environ, start_response):
    """WSGI application entry point."""
    
    method = environ.get('REQUEST_METHOD', 'GET')
    path = environ.get('PATH_INFO', '/')
    query_string = environ.get('QUERY_STRING', '')
    
    try:
        params = urllib.parse.parse_qs(query_string)
        
        # Route: GET /authorize → initiate device flow
        if path in ['/', '/authorize']:
            user_email = params.get('email', ['jsr_critchley@hotmail.com'])[0]
            
            flow_id, flow = acquire_token_with_device_flow(user_email)
            if not flow_id:
                status = '500 Internal Server Error'
                body = json.dumps(flow)
                response_headers = [('Content-Type', 'application/json')]
                start_response(status, response_headers)
                return [body.encode('utf-8')]
            
            # Return HTML page with device flow instructions
            message = flow.get('message', 'No message')
            # Extract just the URL from the MSAL message
            m = re.search(r'https?://\S+', message)
            device_url = m.group(0).rstrip('.') if m else 'https://www.microsoft.com/devicelogin'
            user_code = flow.get('user_code')
            
            body = f"""<!DOCTYPE html>
<html>
<head>
    <title>Outlook Token Authorization</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: #f5f5f5; padding: 20px; }}
        .container {{ max-width: 600px; margin: 0 auto; }}
        h1 {{ color: #333; margin-bottom: 30px; font-size: 28px; }}
        .step {{ background: white; padding: 30px; border-radius: 8px; margin-bottom: 20px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); }}
        .step-number {{ display: inline-block; background: #0078d4; color: white; width: 40px; height: 40px; line-height: 40px; text-align: center; border-radius: 50%; font-weight: bold; margin-right: 15px; }}
        .step-title {{ font-size: 18px; font-weight: 600; color: #333; margin-bottom: 15px; }}
        .button {{ display: inline-block; background: #0078d4; color: white; padding: 12px 24px; border: none; border-radius: 5px; cursor: pointer; font-size: 16px; font-weight: 600; text-decoration: none; margin-right: 10px; transition: background 0.2s; }}
        .button:hover {{ background: #005a9e; }}
        .code-box {{ background: #e8f4f8; border: 3px solid #0078d4; padding: 18px; border-radius: 8px; font-size: 36px; font-weight: bold; text-align: center; font-family: "Courier New", monospace; letter-spacing: 4px; margin: 15px 0; cursor: pointer; user-select: all; }}
        .code-box:hover {{ background: #d0eaf5; }}
        .copy-hint {{ font-size: 13px; color: #666; margin-bottom: 10px; }}
        .status {{ margin-top: 30px; padding: 20px; background: #fff3cd; border-left: 4px solid #ffc107; border-radius: 4px; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>Outlook Token Authorization</h1>
        
        <div class="step">
            <div>
                <span class="step-number">1</span>
                <span class="step-title">Copy your code</span>
            </div>
            <div class="code-box" onclick="copyCode(this)" title="Click to copy">{user_code}</div>
            <div class="copy-hint">Click the code to copy it</div>
        </div>
        
        <div class="step">
            <div>
                <span class="step-number">2</span>
                <span class="step-title">Open Microsoft and enter the code</span>
            </div>
            <button class="button" onclick="openAuthWindow()">Open Microsoft Device Login</button>
            <p style="margin-top: 12px; color: #666;">Paste the code when prompted, then approve the permission request. This page auto-updates when done.</p>
        </div>
        
        <div class="status">
            <div class="status-text" id="status">
                ⏳ Waiting for authorization... (checking every 2 seconds)
            </div>
        </div>
    </div>
    
    <script>
        const flowId = "{flow_id}";
        const deviceUrl = "{device_url}";
        let authWindow = null;
        
        function copyCode(el) {{
            const code = el.textContent.trim();
            navigator.clipboard.writeText(code).then(() => {{
                el.style.background = '#c8f0c8';
                setTimeout(() => el.style.background = '', 1000);
            }});
        }}
        
        function openAuthWindow() {{
            // Open in a popup instead of new tab
            authWindow = window.open(deviceUrl, 'msauth', 'width=600,height=800,resizable=yes');
            if (!authWindow) {{
                alert('Popup blocked. Please allow popups or visit the link manually.');
            }}
        }}
        
        function checkStatus() {{
            fetch(`/authorize-outlook/status?flow_id=${{flowId}}`)
                .then(r => r.json())
                .then(data => {{
                    const statusDiv = document.getElementById('status');
                    if (data.completed) {{
                        statusDiv.innerHTML = `
                            <div style="color: green; font-weight: bold; font-size: 18px;">✓ Token Saved to WebDAV</div>
                            <p style="margin-top: 15px;"><strong>User Email:</strong> {user_email}</p>
                            <p><strong>Saved to:</strong> <code style="background: #f0f0f0; padding: 4px 8px; border-radius: 3px;">${{data.webdav_path}}</code></p>
                            <p style="margin-top: 15px;"><strong>For ~/.netrc (permissions 600):</strong></p>
                            <pre style="background: #f5f5f5; padding: 15px; overflow-x: auto; border-radius: 4px; border: 1px solid #ddd;">${{data.netrc}}</pre>
                        `;
                        // Auto-close popup if it exists
                        if (authWindow) {{
                            setTimeout(() => authWindow.close(), 1000);
                        }}
                    }} else if (data.error) {{
                        statusDiv.innerHTML = `<div style="color: red;"><strong>Error:</strong> ${{data.error}}</div>`;
                    }} else {{
                        statusDiv.innerHTML = `⏳ Waiting for authentication... (checked at ${{new Date().toLocaleTimeString()}})`;
                        setTimeout(checkStatus, 2000);
                    }}
                }})
                .catch(e => {{
                    document.getElementById('status').innerHTML = `<div style="color: red;"><strong>Error:</strong> ${{e}}</div>`;
                }});
        }}
        
        // Start auto-checking immediately
        checkStatus();
    </script>
</body>
</html>"""
            
            status = '200 OK'
            response_headers = [('Content-Type', 'text/html; charset=utf-8')]
            start_response(status, response_headers)
            return [body.encode('utf-8')]
        
        # Route: GET /status?flow_id=... → check device flow status
        elif path == '/status':
            flow_id = params.get('flow_id', [None])[0]
            if not flow_id:
                status = '400 Bad Request'
                body = json.dumps({"error": "flow_id required"})
                response_headers = [('Content-Type', 'application/json')]
                start_response(status, response_headers)
                return [body.encode('utf-8')]
            
            result = poll_device_flow_completion(flow_id)
            
            if result is None:
                # Still pending
                body = json.dumps({"completed": False})
            elif "error" in result:
                # Error
                body = json.dumps({"completed": False, "error": result.get("error")})
            else:
                # Success
                user_email = result.get('user_email', 'unknown')
                refresh_token = result.get('refresh_token', '')
                netrc_entry = format_netrc_entry(refresh_token, user_email)
                webdav_path = f'/var/www/webdav/outlook_tokens/{TokenStore._safe_filename(user_email)}.json'
                body = json.dumps({
                    "completed": True,
                    "refresh_token": refresh_token,
                    "netrc": netrc_entry,
                    "webdav_path": webdav_path
                })
            
            response_headers = [('Content-Type', 'application/json')]
            start_response('200 OK', response_headers)
            return [body.encode('utf-8')]
        
        # Route: GET /list → show stored tokens
        elif path == '/list':
            tokens = TokenStore.list_tokens()
            body = f"""<!DOCTYPE html>
<html>
<head>
    <title>Stored Outlook Tokens</title>
    <style>
        body {{ font-family: sans-serif; margin: 40px; }}
        table {{ border-collapse: collapse; width: 100%; }}
        th, td {{ border: 1px solid #ddd; padding: 10px; text-align: left; }}
        th {{ background: #0078d4; color: white; }}
    </style>
</head>
<body>
    <h1>Stored Outlook Tokens</h1>
    <table>
        <tr><th>User Email</th><th>Expires In</th><th>Saved At</th></tr>
"""
            for token in tokens:
                saved = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(token.get('saved_at', 0)))
                body += f"<tr><td>{token.get('user_email')}</td><td>{token.get('expires_in')} sec</td><td>{saved}</td></tr>\n"
            
            body += """
    </table>
    <p><a href="/authorize-outlook/authorize">Authorize New Account</a></p>
</body>
</html>"""
            
            response_headers = [('Content-Type', 'text/html; charset=utf-8')]
            start_response('200 OK', response_headers)
            return [body.encode('utf-8')]
        
        else:
            status = '404 Not Found'
            body = "Not found"
            response_headers = [('Content-Type', 'text/plain')]
            start_response(status, response_headers)
            return [body.encode('utf-8')]
    
    except Exception as e:
        logger.exception("Unhandled exception")
        status = '500 Internal Server Error'
        body = json.dumps({"error": str(e)})
        response_headers = [('Content-Type', 'application/json')]
        start_response(status, response_headers)
        return [body.encode('utf-8')]


if __name__ == '__main__':
    # For testing with a simple server
    from wsgiref.simple_server import make_server
    
    print(f"Starting Outlook OAuth WSGI server on localhost:8024")
    print(f"Device flow (same as get_pop_refresh_token.py)")
    print(f"Visit: http://localhost:8024/authorize")
    
    server = make_server('127.0.0.1', 8024, application)
    server.serve_forever()
