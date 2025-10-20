#!/usr/bin/python3
"""
POP3 -> gdbm synchroniser (XOAUTH2).

- Uses UIDL to detect messages and LIST for byte sizes.
- Stores each message in a GNU dbm (via user's gdata.gdata) as JSON:
    key   = UIDL (str)
    value = {"size": int, "mail": str}  # `mail` is raw bytes decoded with latin-1 (1:1 round-trippable)

Requirements:
  - You already have a refresh token stored in ~/.netrc for the machine
    (account field like "MSAL:<client_id>", password is the refresh_token).
  - pip install requests
  - Your Outlook.com mailbox has POP enabled.

Example:
  python3 pop_sync_gdbm.py --dbfile ~/.email.gdbm
"""

import argparse
import base64
import netrc
import os
import socket
import ssl
import sys
import json
import time
import stat

import requests  # pip install requests
import gdata  # import gdata, use gdata.gdata_raw and gdata.gdata as needed
import process_emails  # for do_processing
from process_lock import ProcessLock

#import pdb

DEFAULT_MACHINE = "outlook.office365.com"
DEFAULT_HOST = "outlook.office365.com"
DEFAULT_PORT = 995
TIMEOUT = 30
DEFAULT_AUTHORITY = "https://login.microsoftonline.com/consumers"
POP_SCOPE = "https://outlook.office.com/POP.AccessAsUser.All"
# Handle dbfile defaults
DEFAULT_DBFILE = "~/.email3.mail.gdbm"
    


class Pop3TLS:
    def __enter__(self):
        return self.connect()

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False
    def __init__(self, host, port=DEFAULT_PORT, timeout=TIMEOUT, show=True):
        self.host, self.port, self.timeout, self.show = host, port, timeout, show
        self.sock = None
        self.file = None  # buffered reader

    def connect(self):
        raw = socket.create_connection((self.host, self.port), timeout=self.timeout)
        ctx = ssl.create_default_context()
        self.sock = ctx.wrap_socket(raw, server_hostname=self.host)
        self.file = self.sock.makefile("rb", buffering=0)
        banner = self._readline()
        print(banner.decode("utf-8", "replace").rstrip())
        return self

    def close(self):
        try:
            if self.sock:
                self.sock.close()
        finally:
            self.sock = None
            self.file = None

    def _sendline(self, line):
        if not line.endswith("\r\n"):
            line += "\r\n"
        self.sock.sendall(line.encode("utf-8"))

    def _readline(self):
        buf = bytearray()
        while True:
            b = self.file.read(1)
            if not b:
                break
            buf += b
            if len(buf) >= 2 and buf[-2:] == b"\r\n":
                break
        return bytes(buf)

    def _read_multiline(self):
        lines = []
        while True:
            line = self._readline()
            if line == b".\r\n":
                break
            if line.startswith(b".."):  # dot-stuffing unescape
                line = line[1:]
            lines.append(line)
        return lines

    def send_cmd(self, cmd, show=None):
        if show is None:
            show = self.show
        if show:
            print(f">>> {cmd}")
        self._sendline(cmd)
        resp = self._readline()
        print(resp.decode("utf-8", "replace").rstrip())
        return resp

    def expect_ok(self, resp, what=""):
        if not resp.startswith(b"+OK"):
            msg = resp.decode("utf-8", "replace").rstrip()
            raise SystemExit(f"{what} failed: {msg}")

def read_netrc(machine):
    nrc_path = os.path.expanduser("~/.netrc")
    try:
        auth = netrc.netrc(nrc_path).authenticators(machine)
    except FileNotFoundError:
        raise SystemExit(f"No ~/.netrc found at {nrc_path}")
    if not auth:
        raise SystemExit(f"No entry for machine '{machine}' in ~/.netrc")
    login, account, password = auth
    if not login or not password:
        raise SystemExit(f"~/.netrc entry for '{machine}' missing login or password")
    return login, account, password


def parse_client_id_from_account(account):
    if not account:
        return None
    if account.upper().startswith("MSAL:"):
        return account.split(":", 1)[1] or None
    if account.upper() == "MSAL":
        return None
    return None


def acquire_access_token_via_refresh(client_id, refresh_token, authority, scope):
    token_url = authority.rstrip("/") + "/oauth2/v2.0/token"
    data = {
        "client_id": client_id,
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "scope": scope,
    }
    r = requests.post(token_url, data=data, timeout=30)
#    print('-->', r.text)
    try:
        js = r.json()
    except Exception:
        r.raise_for_status()
        raise
    if r.status_code != 200 or "access_token" not in js:
        err = js.get("error_description") or js
        raise SystemExit(f"Refresh-token exchange failed: {err}")
    return r.text,js["access_token"]


def auth_xoauth2(pop, user, access_token):
    resp = pop.send_cmd("AUTH XOAUTH2")
    if not resp.startswith(b"+"):
        raise SystemExit(f"Server rejected AUTH XOAUTH2: {resp!r}")
    xoauth = f"user={user}\x01auth=Bearer {access_token}\x01\x01".encode()
    pop._sendline(base64.b64encode(xoauth).decode())
    resp = pop._readline()
    print(resp.decode("utf-8", "replace").rstrip())
    pop.expect_ok(resp, "XOAUTH2")


def get_uidl_map(pop):
    """Return {uidl: (msgnum, uidl)} -- using UIDL for stable IDs."""
    resp = pop.send_cmd("UIDL")
    pop.expect_ok(resp, "UIDL")
    mapping = {}
    for ln in pop._read_multiline():
        s = ln.strip()
        if not s:
            continue
        parts = s.split()
        if len(parts) >= 2 and parts[0].isdigit():
            num = int(parts[0]); uidl = parts[1]
            mapping[uidl] = num
    return mapping


#def get_size_map(pop):
#    """Return {msgnum: size} from LIST."""
#    resp = pop.send_cmd("LIST")
#    pop.expect_ok(resp, "LIST")
#    sizes = {}
#    for ln in pop._read_multiline():
#        s = ln.decode("utf-8", "replace").strip()
#        if not s:
#            continue
#        parts = s.split()
#        if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
#            sizes[int(parts[0])] = int(parts[1])
#    return sizes


def fetch_message_bytes(pop, msgnum):
    """RETR msgnum and return raw bytes (without the final dot line)."""
    resp = pop.send_cmd(f"RETR {msgnum}")
    pop.expect_ok(resp, "RETR")
    lines = pop._read_multiline()
    return b"".join(lines)  # each line already has CRLF

def del_message(pop, msgnum):
    """DELE msgnum."""
    resp = pop.send_cmd(f"DELE {msgnum}")
    pop.expect_ok(resp, "DELE")

def main(
    machine=None,
    host="outlook.office365.com",
    port=995,
    user=None,
    client_id=None,
    authority="https://login.microsoftonline.com/consumers",
    dbfile=os.path.expanduser(DEFAULT_DBFILE),
    show=True,
    reprocess=False
):
    # Prevent concurrent execution
    lock_file = "/tmp/popit3.lock"
    try:
        with ProcessLock(lock_file):
            _main_impl(machine, host, port, user, client_id, authority, dbfile, show, reprocess)
    except RuntimeError as e:
        print(f"Error: {e}")
        print("Another popit3 process is already running. Exiting.")
        sys.exit(1)


def _main_impl(
    machine=None,
    host="outlook.office365.com",
    port=995,
    user=None,
    client_id=None,
    authority="https://login.microsoftonline.com/consumers",
    dbfile=os.path.expanduser(DEFAULT_DBFILE),
    show=True,
    reprocess=False
):
    # If machine is not specified, use host value
    if machine is None:
        machine = host

    login_name, account, secret = read_netrc(machine)
    if user is None:
        user = login_name
    if client_id is None:
        client_id = parse_client_id_from_account(account)
    if not client_id:
        raise SystemExit("client_id not provided. Pass --client-id or set account 'MSAL:<client_id>' in ~/.netrc")
    refresh_token = secret
    
    access_token_file=os.path.expanduser(f'~/.{machine}_token')
    token=None
    if os.path.isfile(access_token_file):
        with open(access_token_file, "r") as token_fd:
            token_data=json.load(token_fd)
        if time.time() - os.stat(access_token_file)[stat.ST_MTIME]<token_data['expires_in']:
            token=token_data["access_token"] 
    # Mint an access token via refresh token
    if token is None:
        r_text,token = acquire_access_token_via_refresh(client_id, refresh_token, authority, POP_SCOPE)
        with open(access_token_file, "w") as token_fd:
            token_fd.write(r_text)

    with gdata.gdata_raw(gdbm_file=dbfile) as maildb, Pop3TLS(host=host, port=port, show=show) as pop:
        auth_xoauth2(pop, user, token)

        # Build current server view
        uidl_map = get_uidl_map(pop)           # {uidl: num}
        #size_map = get_size_map(pop)           # {num: size}

        # Fetch new mail
        mails_to_process = []
        for uidl, num in uidl_map.items():
            #size = size_map.get(num, None)
            if uidl in maildb:
                if reprocess:
                    raw=maildb[uidl]
                else:
                    continue
            else:
                raw = fetch_message_bytes(pop, num)  # bytes

                maildb[uidl] = raw  # store raw bytes
            mails_to_process.append((uidl, raw#, size
                                ))
        # Call processing function for new emails
        todelete=process_emails.do_processing(mails_to_process, maildb)

        with gdata.gdata_raw(gdbm_file=dbfile+'.save') as oldmaildb:
            for delthis in todelete:
                if isinstance(delthis, int):
                    delthis=str(delthis).encode('ascii') # only 0-9 anyway
                elif isinstance(delthis, str):
                    delthis=delthis.encode('utf-8')
                del_message(pop, uidl_map[delthis])
                oldmaildb[delthis]=maildb[delthis]
                del maildb[delthis]
                del uidl_map[delthis]
            

        # WILL NOT DELE
        # if QUIT not sent
        # so comment for testing
        pop.send_cmd("QUIT")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Mirror POP3 mailbox into a gdbm file using UIDL keys (XOAUTH2)." )
    p.add_argument("--machine", help=f"netrc machine (default: {DEFAULT_MACHINE})")
    p.add_argument("--host", help=f"POP3 host (default: {DEFAULT_HOST})")
    p.add_argument("--port", type=int, help=f"POP3 TLS port (default: {DEFAULT_PORT})")
    p.add_argument("--user", help="Override username (default: login from ~/.netrc)")
    p.add_argument("--client-id", help="Azure app client_id (or encode in netrc account as MSAL:<client_id>)")
    p.add_argument("--authority", help=f"AAD authority (default {DEFAULT_AUTHORITY})")
    p.add_argument("--dbfile", help=f"Path to gdbm file (default {DEFAULT_DBFILE})")
    p.add_argument("--show", action="store_true", help="Echo commands/replies (default True)")
    p.add_argument("--no-show", dest="show", action="store_false", help="Disable echo")

    p.add_argument("--reprocess", action="store_true", help="Reprocess mails already seen")
    p.add_argument("--no-reprocess", dest="reprocess", action="store_false", help="Disable reprocess")
    p.set_defaults(show=None, reprocess=None)

    ns = p.parse_args()
    kwargs = {k: v for k, v in vars(ns).items() if v is not None}
    print(kwargs)
    main(**kwargs)
