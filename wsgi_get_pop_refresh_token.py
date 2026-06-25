#!/usr/bin/python3
"""
WSGI script to acquire an Outlook POP refresh token via OAuth2 auth code flow.

Bare URL:   redirect user to Microsoft login
Callback:   exchange code for token, write credentials file, show result

Environment variables:
  CLIENT_ID     MSAL app (client) ID [default: 60da67f7-5fde-4e85-baf3-ab28d0c8e034]
  AUTH_OUTPUT   Output path for .netrc-format credentials [default: /tmp/auth.txt]
  REDIRECT_URI  Override auto-detected callback URL
  GDATA_FILE    Path to local gdbm file for session storage [default: /tmp/wsgi_pop_sessions.gdbm]
  GDATA_URL     gdata-server base URL (overrides GDATA_FILE if set)
  POST          Use response_mode=form_post (Microsoft POSTs code back): yes/no [default: no]

URL parameters (on the initial bare request):
  auth_user=... Email address to record in credentials [default: jsr_critchley@hotmail.com]
"""

import os
import sys
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import msal
import gd as gdata

DEFAULT_CLIENT_ID = '60da67f7-5fde-4e85-baf3-ab28d0c8e034'
DEFAULT_USER = 'jsr_critchley@hotmail.com'
AUTHORITY = 'https://login.microsoftonline.com/consumers'
SCOPE = 'https://outlook.office.com/POP.AccessAsUser.All'
DEFAULT_OUTPUT = '/home/dav/private/creds/auth.txt'

GDATA_FLOW_PREFIX = 'wsgi_pop_flow:'
GDATA_RESULT_PREFIX = 'wsgi_pop_result:'


# ---------------------------------------------------------------------------
# gdata helpers
# ---------------------------------------------------------------------------

def _open_db():
    """Return a gdata instance (context manager) for session storage."""
    url = os.environ.get('GDATA_URL')
    return (
            gdata.gdata(url=url)
        if
            url
        else
            gdata.gdata(gdbm_file=os.environ.get('GDATA_FILE', '/tmp/wsgi_pop_sessions.gdbm'))
        )


# ---------------------------------------------------------------------------
# WSGI helpers
# ---------------------------------------------------------------------------

def _base_url(environ):
    """
    Return the canonical URL of this script (no query string).
    REDIRECT_URI env var takes precedence; otherwise derived from WSGI environ.
    """
    override = os.environ.get('REDIRECT_URI')
    if override:
        return override.split('?')[0].rstrip('/')

    scheme = environ.get('wsgi.url_scheme', 'http')
    host = environ.get('HTTP_HOST')
    if not host:
        host = environ.get('SERVER_NAME', 'localhost')
        port = environ.get('SERVER_PORT', '80')
        if (scheme == 'http' and port != '80') or (scheme == 'https' and port != '443'):
            host = f"{host}:{port}"

    # SCRIPT_NAME is the mount path of this WSGI app/script
    script = environ.get('SCRIPT_NAME', '')
    return f"{scheme}://{host}{script}"


def _respond(start_response, status, html):
    body = html.encode('utf-8')
    start_response(status, [
        ('Content-Type', 'text/html; charset=utf-8'),
        ('Content-Length', str(len(body))),
    ])
    return [body]


def _redirect(start_response, url):
    start_response('302 Found', [
        ('Location', url),
        ('Content-Length', '0'),
    ])
    return [b'']


# ---------------------------------------------------------------------------
# HTML helpers
# ---------------------------------------------------------------------------

def _page(title, body):
    return f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>{title}</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    body {{ font-family: monospace; padding: 1em; max-width: 900px; margin: auto; }}
    pre  {{ background: #f4f4f4; padding: 1em; overflow-x: auto;
            white-space: pre-wrap; word-break: break-all; }}
    button {{ margin-top: .5em; padding: .4em .9em; cursor: pointer; font-size: 1em; }}
  </style>
</head>
<body>
{body}
</body>
</html>"""


def _h(text):
    """HTML-escape a string."""
    return (text
            .replace('&', '&amp;')
            .replace('<', '&lt;')
            .replace('>', '&gt;')
            .replace('"', '&quot;'))


def _error_page(heading, detail):
    return _page('Error', f'<h2>{_h(heading)}</h2><p>{_h(detail)}</p>')


# ---------------------------------------------------------------------------
# Credential formatting
# ---------------------------------------------------------------------------

def _format_netrc(client_id, user, refresh_token):
    return (
        f"machine outlook.office365.com\n"
        f"login {user}\n"
        f"account MSAL:{client_id}\n"
        f"password {refresh_token}"
    )


# ---------------------------------------------------------------------------
# Auth flow stages
# ---------------------------------------------------------------------------

def _start_auth(environ, start_response, client_id, base_url, user, use_post):
    """Initiate MSAL auth code flow and redirect to Microsoft login."""
    app = msal.PublicClientApplication(client_id, authority=AUTHORITY)

    kwargs = dict(scopes=[SCOPE], redirect_uri=base_url)
    if use_post:
        kwargs['response_mode'] = 'form_post'

    try:
        flow = app.initiate_auth_code_flow(**kwargs)
    except Exception as e:
        return _respond(start_response, '500 Internal Server Error',
                        _error_page('MSAL error', str(e)))

    state_key = flow['state']
    try:
        with _open_db() as db:
            db[GDATA_FLOW_PREFIX + state_key] = {'flow': flow, 'user': user}
    except Exception as e:
        return _respond(start_response, '500 Internal Server Error',
                        _error_page('Session store error', str(e)))

    return _redirect(start_response, flow['auth_uri'])


def _handle_callback(start_response, client_id, auth_output, base_url,
                     state, response_params, use_post):
    """
    Exchange auth code for token, write credentials file, then either:
      - (GET mode)  redirect to ?done=1&state=...
      - (POST mode) render the result page directly
    """
    # Retrieve stored flow from gdata
    try:
        with _open_db() as db:
            session = db.get(GDATA_FLOW_PREFIX + state)
    except Exception as e:
        return _respond(start_response, '500 Internal Server Error',
                        _error_page('Session read error', str(e)))

    if not session:
        return _respond(start_response, '400 Bad Request',
                        _page('Session Not Found',
                              '<p>Unknown or expired session. '
                              'Please <a href="">start again</a>.</p>'))

    flow = session['flow']
    user = session.get('user', DEFAULT_USER)

    # Exchange code for tokens
    app = msal.PublicClientApplication(client_id, authority=AUTHORITY)
    result = app.acquire_token_by_auth_code_flow(flow, response_params)

    if 'refresh_token' not in result:
        err = result.get('error_description') or result.get('error') or str(result)
        return _respond(start_response, '502 Bad Gateway',
                        _page('Token Error',
                              f'<h2>Token acquisition failed</h2><pre>{_h(err)}</pre>'))

    refresh_token = result['refresh_token']
    netrc = _format_netrc(client_id, user, refresh_token)

    # Write credentials file
    try:
        with open(auth_output, 'w') as f:
            f.write(netrc + '\n')
        os.chmod(auth_output, 0o600)
    except Exception as e:
        return _respond(start_response, '500 Internal Server Error',
                        _error_page(f'Could not write {auth_output}', str(e)))

    # Persist result in gdata and clean up flow entry
    try:
        with _open_db() as db:
            db[GDATA_RESULT_PREFIX + state] = {
                'client_id': client_id,
                'user': user,
                'refresh_token': refresh_token,
            }
            try:
                del db[GDATA_FLOW_PREFIX + state]
            except KeyError:
                pass
    except Exception:
        pass  # Non-fatal: credentials are already written to disk

    if use_post:
        # Render result directly (we already have it)
        return _render_result(start_response, client_id, user, refresh_token, auth_output)
    else:
        done_url = base_url + '?' + urllib.parse.urlencode({'done': '1', 'state': state})
        return _redirect(start_response, done_url)


def _show_result_from_gdata(start_response, state, client_id, auth_output):
    """Read result from gdata and render the result page (used in GET mode done step)."""
    try:
        with _open_db() as db:
            stored = db.get(GDATA_RESULT_PREFIX + state)
    except Exception as e:
        return _respond(start_response, '500 Internal Server Error',
                        _error_page('Result read error', str(e)))

    if not stored:
        return _respond(start_response, '404 Not Found',
                        _page('Not Found',
                              '<p>Result not found. Auth may not have completed yet.</p>'))

    return _render_result(start_response,
                          stored['client_id'], stored['user'],
                          stored['refresh_token'], auth_output)


def _render_result(start_response, client_id, user, refresh_token, auth_output):
    """Render the success page showing the credentials."""
    netrc = _format_netrc(client_id, user, refresh_token)
    body = f"""<h2>Authentication complete</h2>
<p>Credentials written to <code>{_h(auth_output)}</code> (mode 600)</p>
<h3>Copy/paste credentials:</h3>
<pre id="creds">{_h(netrc)}</pre>
<button onclick="navigator.clipboard.writeText(document.getElementById('creds').innerText)
    .then(()=>this.textContent='Copied!')
    .catch(()=>this.textContent='Copy failed')">Copy to clipboard</button>
"""
    return _respond(start_response, '200 OK', _page('Auth Complete', body))


# ---------------------------------------------------------------------------
# Main WSGI entry point
# ---------------------------------------------------------------------------

def application(environ, start_response):
    client_id = os.environ.get('CLIENT_ID', DEFAULT_CLIENT_ID)
    auth_output = os.environ.get('AUTH_OUTPUT', DEFAULT_OUTPUT)
    use_post = os.environ.get('POST', 'no').lower() == 'yes'
    method = environ.get('REQUEST_METHOD', 'GET').upper()
    base_url = _base_url(environ)

    # -- POST callback (response_mode=form_post; Microsoft sends code in body) ----
    if use_post and method == 'POST':
        length = int(environ.get('CONTENT_LENGTH', 0) or 0)
        raw = environ['wsgi.input'].read(length).decode('utf-8')
        pp = urllib.parse.parse_qs(raw, keep_blank_values=True)

        def _pp(name, default=''):
            return (pp.get(name) or [default])[0]

        if _pp('error'):
            return _respond(start_response, '400 Bad Request',
                            _page('Auth Error',
                                  f'<h2>Auth Error</h2>'
                                  f'<p>{_h(_pp("error"))}: {_h(_pp("error_description"))}</p>'))

        state = _pp('state')
        code = _pp('code')
        if not state or not code:
            return _respond(start_response, '400 Bad Request',
                            _page('Bad Request',
                                  '<p>Missing <code>state</code> or <code>code</code> '
                                  'in POST body.</p>'))

        return _handle_callback(start_response, client_id, auth_output, base_url,
                                state, {'code': code, 'state': state}, use_post)

    # -- GET request -----------------------------------------------------------
    qs = urllib.parse.parse_qs(environ.get('QUERY_STRING', ''), keep_blank_values=True)

    def _qp(name, default=''):
        return (qs.get(name) or [default])[0]

    error = _qp('error')
    if error:
        return _respond(start_response, '400 Bad Request',
                        _page('Auth Error',
                              f'<h2>Auth Error</h2>'
                              f'<p>{_h(error)}: {_h(_qp("error_description"))}</p>'))

    done = _qp('done')
    state = _qp('state')
    code = _qp('code')

    # Done page: show stored result
    if done and state:
        return _show_result_from_gdata(start_response, state, client_id, auth_output)

    # OAuth callback (GET / query-string mode)
    if code and state:
        return _handle_callback(start_response, client_id, auth_output, base_url,
                                state, {'code': code, 'state': state}, use_post)

    # Initial bare request: start OAuth flow
    auth_user = _qp('auth_user', DEFAULT_USER)
    return _start_auth(environ, start_response, client_id, base_url, auth_user, use_post)
