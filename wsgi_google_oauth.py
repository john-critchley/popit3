#!/usr/bin/env python3
"""
WSGI OAuth handler for Google token renewal via authorization code flow.

GET /authorize-google/          → redirect to Google consent page
GET /authorize-google/callback  → exchange code, write ~/.google_token.json

Environment variables:
  GOOGLE_TOKEN_FILE    Path to write token JSON (default: ~/. google_token.json)
  GOOGLE_SECRETS_FILE  Path to ansible secrets.yml  (default: ~/ansible/secrets.yml)
  REDIRECT_URI         Callback URL registered in Google Cloud Console (recommended: set in Apache)

Register https://www.critchley.biz/authorize-google/callback as an authorized
redirect URI in Google Cloud Console under the OAuth 2.0 client credentials.
"""

import json
import os
import re
import secrets
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

import yaml

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

SCOPES = [
    'https://www.googleapis.com/auth/gmail.modify',
    'https://www.googleapis.com/auth/calendar',
    'https://www.googleapis.com/auth/drive',
]

AUTH_URI  = 'https://accounts.google.com/o/oauth2/v2/auth'
TOKEN_URI = 'https://oauth2.googleapis.com/token'

STATE_DIR = '/tmp/google_auth_states'


def _token_file():
    return os.environ.get('GOOGLE_TOKEN_FILE', os.path.expanduser('~/.google_token.json'))


def _secrets_file():
    return os.environ.get('GOOGLE_SECRETS_FILE', os.path.expanduser('~/ansible/secrets.yml'))


# ---------------------------------------------------------------------------
# Secrets / token helpers
# ---------------------------------------------------------------------------

def _load_secrets():
    with open(_secrets_file()) as f:
        return yaml.safe_load(f)


def _save_refresh_token(refresh_token):
    path = _secrets_file()
    with open(path) as f:
        text = f.read()
    text = re.sub(
        r'^(google_refresh_token:\s*).*$',
        f'google_refresh_token: "{refresh_token}"',
        text, flags=re.MULTILINE,
    )
    with open(path, 'w') as f:
        f.write(text)


def _write_token_file(token_data):
    path = _token_file()
    with open(path, 'w') as f:
        json.dump(token_data, f, indent=2)
    os.chmod(path, 0o600)


# ---------------------------------------------------------------------------
# CSRF state helpers
# ---------------------------------------------------------------------------

def _store_state(state):
    os.makedirs(STATE_DIR, mode=0o700, exist_ok=True)
    open(os.path.join(STATE_DIR, state), 'w').close()


def _consume_state(state):
    path = os.path.join(STATE_DIR, state)
    if not os.path.exists(path):
        return False
    os.remove(path)
    return True


# ---------------------------------------------------------------------------
# OAuth helpers
# ---------------------------------------------------------------------------

def _redirect_uri(environ):
    override = os.environ.get('REDIRECT_URI')
    if override:
        return override
    scheme = environ.get('wsgi.url_scheme', 'https')
    host   = environ.get('HTTP_HOST', 'www.critchley.biz')
    script = environ.get('SCRIPT_NAME', '/authorize-google')
    return f'{scheme}://{host}{script}/callback'


def _auth_url(client_id, redirect_uri, state):
    params = {
        'client_id':     client_id,
        'redirect_uri':  redirect_uri,
        'response_type': 'code',
        'scope':         ' '.join(SCOPES),
        'access_type':   'offline',
        'prompt':        'consent',
        'state':         state,
    }
    return AUTH_URI + '?' + urllib.parse.urlencode(params)


def _exchange_code(client_id, client_secret, redirect_uri, code):
    """POST code to token endpoint, return parsed JSON."""
    body = urllib.parse.urlencode({
        'code':          code,
        'client_id':     client_id,
        'client_secret': client_secret,
        'redirect_uri':  redirect_uri,
        'grant_type':    'authorization_code',
    }).encode()
    req = urllib.request.Request(TOKEN_URI, data=body, method='POST')
    req.add_header('Content-Type', 'application/x-www-form-urlencoded')
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return json.loads(e.read().decode())


# ---------------------------------------------------------------------------
# HTML helpers
# ---------------------------------------------------------------------------

def _h(s):
    return str(s).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


_STYLE = """
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
       background: #f5f5f5; padding: 40px 20px; }
.card { max-width: 600px; margin: 0 auto; background: white; padding: 36px;
        border-radius: 10px; box-shadow: 0 2px 12px rgba(0,0,0,.1); }
h1 { font-size: 24px; color: #333; margin-bottom: 24px; }
p  { color: #555; line-height: 1.6; margin-bottom: 12px; }
.ok  { color: #1a7f37; font-weight: 600; font-size: 18px; margin-bottom: 16px; }
.err { color: #c0392b; font-weight: 600; font-size: 18px; margin-bottom: 16px; }
pre  { background: #f4f4f4; border: 1px solid #ddd; border-radius: 6px;
       padding: 14px; font-size: 13px; overflow-x: auto; }
"""


def _page(title, body_html):
    return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"><title>{_h(title)}</title>
<style>{_STYLE}</style></head>
<body><div class="card">{body_html}</div></body>
</html>""".encode()


# ---------------------------------------------------------------------------
# WSGI application
# ---------------------------------------------------------------------------

def application(environ, start_response):
    path = environ.get('PATH_INFO', '/')
    qs   = urllib.parse.parse_qs(environ.get('QUERY_STRING', ''))

    try:
        # ── Initiate flow ──────────────────────────────────────────────────
        if path in ('/', ''):
            sec         = _load_secrets()
            state       = secrets.token_urlsafe(16)
            redir       = _redirect_uri(environ)
            url         = _auth_url(sec['google_client_id'], redir, state)
            _store_state(state)
            start_response('302 Found', [('Location', url), ('Cache-Control', 'no-store')])
            return [b'']

        # ── Handle callback ────────────────────────────────────────────────
        elif path == '/callback':
            error = qs.get('error', [None])[0]
            if error:
                start_response('400 Bad Request', [('Content-Type', 'text/html; charset=utf-8')])
                return [_page('Auth Error', f'<h1>Google Auth</h1>'
                              f'<p class="err">Error: {_h(error)}</p>')]

            code  = qs.get('code',  [None])[0]
            state = qs.get('state', [None])[0]

            if not code or not state:
                start_response('400 Bad Request', [('Content-Type', 'text/html; charset=utf-8')])
                return [_page('Bad Request', '<h1>Google Auth</h1>'
                              '<p class="err">Missing code or state parameter.</p>')]

            if not _consume_state(state):
                start_response('400 Bad Request', [('Content-Type', 'text/html; charset=utf-8')])
                return [_page('Bad Request', '<h1>Google Auth</h1>'
                              '<p class="err">Invalid or expired state. Try again.</p>')]

            sec   = _load_secrets()
            redir = _redirect_uri(environ)
            result = _exchange_code(sec['google_client_id'], sec['google_client_secret'], redir, code)

            if 'error' in result:
                msg = result.get('error_description', result['error'])
                start_response('502 Bad Gateway', [('Content-Type', 'text/html; charset=utf-8')])
                return [_page('Token Error', f'<h1>Google Auth</h1>'
                              f'<p class="err">Token exchange failed: {_h(msg)}</p>')]

            access_token  = result['access_token']
            refresh_token = result.get('refresh_token', '')
            expires_in    = result.get('expires_in', 3600)
            expiry = (datetime.now(timezone.utc) + timedelta(seconds=expires_in)).isoformat()

            token_data = {
                'token':         access_token,
                'refresh_token': refresh_token,
                'token_uri':     TOKEN_URI,
                'client_id':     sec['google_client_id'],
                'client_secret': sec['google_client_secret'],
                'scopes':        SCOPES,
                'expiry':        expiry,
            }
            _write_token_file(token_data)
            if refresh_token:
                _save_refresh_token(refresh_token)

            body_html = f"""
<h1>Google Auth</h1>
<p class="ok">&#10003; Token saved successfully.</p>
<p>Written to: <code>{_h(_token_file())}</code></p>
<p>Scopes authorised:</p>
<pre>{_h(chr(10).join(SCOPES))}</pre>
<p style="margin-top:20px;">You can close this tab.</p>
"""
            start_response('200 OK', [('Content-Type', 'text/html; charset=utf-8'),
                                      ('Cache-Control', 'no-store')])
            return [_page('Google Auth — Done', body_html)]

        else:
            start_response('404 Not Found', [('Content-Type', 'text/plain')])
            return [b'Not found']

    except Exception as exc:
        import traceback
        tb = traceback.format_exc()
        start_response('500 Internal Server Error', [('Content-Type', 'text/html; charset=utf-8')])
        return [_page('Server Error', f'<h1>Google Auth</h1>'
                      f'<p class="err">Unexpected error:</p><pre>{_h(tb)}</pre>')]


# ---------------------------------------------------------------------------
# Dev server
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    from wsgiref.simple_server import make_server
    port = 8025
    print(f'Google OAuth dev server on http://localhost:{port}/')
    print(f'Set REDIRECT_URI=http://localhost:{port}/callback')
    make_server('127.0.0.1', port, application).serve_forever()
