"""
Google API service clients — Gmail, Calendar, Drive.

Loads credentials from ~/.google_token.json (written by google-auth-setup
or wsgi_google_oauth.py). On RefreshError (expired/revoked refresh token),
falls back to fetching a fresh token from WebDAV, updates the local file,
and retries — matching the same recovery pattern as popit3's Outlook flow.

Usage:
    import google_services
    gmail    = google_services.gmail()
    calendar = google_services.calendar()
    drive    = google_services.drive()
"""
import json
import netrc
import os
from datetime import datetime, timezone

import requests
from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

TOKEN_FILE   = os.path.expanduser("~/.google_token.json")
WEBDAV_URL   = "https://webdav.critchley.biz/google_tokens/google_token.json"
WEBDAV_HOST  = "webdav.critchley.biz"


def _load_token_dict(path=TOKEN_FILE):
    with open(path) as f:
        return json.load(f)


def _save_token_dict(d, path=TOKEN_FILE):
    with open(path, "w") as f:
        json.dump(d, f, indent=2)
    os.chmod(path, 0o600)


def _dict_to_creds(d):
    expiry = None
    if d.get("expiry"):
        expiry = datetime.fromisoformat(d["expiry"])
        # google-auth uses naive utcnow() internally — expiry must be naive UTC
        if expiry.tzinfo is not None:
            expiry = expiry.astimezone(timezone.utc).replace(tzinfo=None)
    return Credentials(
        token         = d.get("token"),
        refresh_token = d["refresh_token"],
        token_uri     = d["token_uri"],
        client_id     = d["client_id"],
        client_secret = d["client_secret"],
        scopes        = d.get("scopes"),
        expiry        = expiry,
    )


def _fetch_token_from_webdav():
    """Fetch fresh token JSON from WebDAV. Returns dict or None."""
    try:
        nrc  = netrc.netrc(os.path.expanduser("~/.netrc"))
        auth = nrc.authenticators(WEBDAV_HOST)
        if not auth:
            print(f"WARNING: no {WEBDAV_HOST} entry in ~/.netrc")
            return None
        wdav_user, _, wdav_pass = auth
        r = requests.get(WEBDAV_URL, auth=(wdav_user, wdav_pass), timeout=10)
        if r.status_code == 404:
            print(f"No Google token at {WEBDAV_URL}")
            return None
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"WARNING: could not fetch Google token from WebDAV: {e}")
        return None


def _load_creds():
    if not os.path.exists(TOKEN_FILE):
        raise FileNotFoundError(
            f"{TOKEN_FILE} not found — run google-auth-setup or visit /google"
        )

    d     = _load_token_dict()
    creds = _dict_to_creds(d)

    if creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            d["token"]  = creds.token
            d["expiry"] = creds.expiry.isoformat() if creds.expiry else None
            _save_token_dict(d)
        except RefreshError:
            print("Google refresh token invalid — checking WebDAV for fresh token...")
            fresh = _fetch_token_from_webdav()
            if not fresh:
                raise
            _save_token_dict(fresh)
            creds = _dict_to_creds(fresh)
            if creds.expired and creds.refresh_token:
                creds.refresh(Request())
                fresh["token"]  = creds.token
                fresh["expiry"] = creds.expiry.isoformat() if creds.expiry else None
                _save_token_dict(fresh)
            print("Google token restored from WebDAV.")

    return creds


def gmail(version="v1"):
    return build("gmail", version, credentials=_load_creds())

def calendar(version="v3"):
    return build("calendar", version, credentials=_load_creds())

def drive(version="v3"):
    return build("drive", version, credentials=_load_creds())
