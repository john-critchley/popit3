#!/usr/bin/env python3
"""
Cleanup cron error emails from hotmail mailbox via POP3.

Searches for emails from cron daemon and mailer-daemon that contain
'check-hibernate' errors, displays results, and deletes them with user confirmation.
"""

import sys
sys.path.insert(0, '.')

import netrc, socket, ssl, base64, requests, os
from typing import List, Tuple, Optional

MACHINE = "outlook.office365.com"
HOST = "outlook.office365.com"
PORT = 995
SCOPE = "https://outlook.office.com/POP.AccessAsUser.All"
AUTHORITY = "https://login.microsoftonline.com/consumers"


class Pop3TLS:
    """POP3 client with TLS authentication."""
    
    def __init__(self, host, port=PORT, timeout=30):
        self.host, self.port, self.timeout = host, port, timeout
        self.sock = None
        self.file = None

    def connect(self):
        raw = socket.create_connection((self.host, self.port), timeout=self.timeout)
        ctx = ssl.create_default_context()
        self.sock = ctx.wrap_socket(raw, server_hostname=self.host)
        self.file = self.sock.makefile("rb", buffering=0)
        self._readline()  # banner
        return self

    def close(self):
        if self.sock:
            self.sock.close()
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
            if line.startswith(b".."):
                line = line[1:]
            lines.append(line)
        return lines

    def send_cmd(self, cmd):
        self._sendline(cmd)
        return self._readline()

    def expect_ok(self, resp, what=""):
        if not resp.startswith(b"+OK"):
            raise RuntimeError(f"{what}: {resp.decode('utf-8', 'replace')}")

    def stat(self) -> int:
        """Get count of messages."""
        resp = self.send_cmd("STAT")
        self.expect_ok(resp, "STAT")
        parts = resp.split()
        return int(parts[1])

    def top(self, msgnum: int, lines: int = 20) -> bytes:
        """Get message headers and first N lines (much faster than RETR)."""
        resp = self.send_cmd(f"TOP {msgnum} {lines}")
        self.expect_ok(resp, f"TOP {msgnum}")
        return b"\n".join(self._read_multiline())

    def retr(self, msgnum: int) -> bytes:
        """Get full message."""
        resp = self.send_cmd(f"RETR {msgnum}")
        self.expect_ok(resp, f"RETR {msgnum}")
        return b"".join(self._read_multiline())

    def dele(self, msgnum: int):
        """Mark message for deletion."""
        resp = self.send_cmd(f"DELE {msgnum}")
        self.expect_ok(resp, f"DELE {msgnum}")

    def quit(self):
        """Close connection and commit deletions."""
        resp = self.send_cmd("QUIT")
        self.expect_ok(resp, "QUIT")


def get_access_token(client_id, refresh_token):
    """Get OAuth2 access token using refresh token."""
    token_url = AUTHORITY.rstrip("/") + "/oauth2/v2.0/token"
    r = requests.post(token_url, data={
        "client_id": client_id,
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "scope": SCOPE,
    }, timeout=30)
    if r.status_code != 200:
        raise RuntimeError(f"Token request failed: {r.text}")
    return r.json()["access_token"]


def auth_xoauth2(pop, user, access_token):
    """Authenticate with XOAUTH2."""
    resp = pop.send_cmd("AUTH XOAUTH2")
    xoauth = f"user={user}\x01auth=Bearer {access_token}\x01\x01".encode()
    pop._sendline(base64.b64encode(xoauth).decode())
    resp = pop._readline()
    pop.expect_ok(resp, "XOAUTH2")


def is_cron_email(headers: str) -> Optional[Tuple[str, str]]:
    """
    Check if email is a cron-related error.
    Returns: (email_type, description) or None
    """
    subject = ""
    sender = ""
    
    for line in headers.split('\n'):
        if line.lower().startswith('subject:'):
            subject = line[8:].strip()
        elif line.lower().startswith('from:'):
            sender = line[5:].strip()
    
    # Type 1: Cron daemon itself
    if subject.lower().startswith('cron'):
        return ("cron-direct", f"{sender} - {subject[:50]}")
    
    # Type 2: Bounce from mailer-daemon or postmaster
    if 'mailer-daemon' in sender.lower() or 'postmaster' in sender.lower():
        # This needs full body check to confirm it's about check-hibernate
        # Return pending status
        return ("bounce-pending", f"{sender} - {subject[:50]}")
    
    return None


def scan_for_cron_emails(pop: Pop3TLS, total_count: int) -> Tuple[List[Tuple[int, str, str]], List[int]]:
    """
    Scan mailbox for cron error emails.
    Returns: (cron_direct_emails, bounce_emails_to_check)
    """
    cron_direct = []
    bounce_pending = []
    
    print(f"Scanning {total_count} messages for cron errors...")
    print("(Using TOP command for speed - headers only)\n")
    
    for msgnum in range(1, total_count + 1):
        if msgnum % 100 == 0:
            print(f"  Progress: {msgnum}/{total_count}...")
        
        try:
            headers = pop.top(msgnum, 20).decode('utf-8', errors='replace')
            result = is_cron_email(headers)
            
            if result:
                email_type, desc = result
                if email_type == "cron-direct":
                    cron_direct.append((msgnum, email_type, desc))
                elif email_type == "bounce-pending":
                    bounce_pending.append(msgnum)
        except Exception as e:
            # Skip errors, continue scanning
            pass
    
    return cron_direct, bounce_pending


def check_bounce_emails(pop: Pop3TLS, bounce_msgids: List[int]) -> List[Tuple[int, str, str]]:
    """Check bounce emails for check-hibernate mentions."""
    cron_bounces = []
    
    if not bounce_msgids:
        return cron_bounces
    
    print(f"\nChecking {len(bounce_msgids)} bounce emails for 'check-hibernate'...")
    
    for i, msgnum in enumerate(bounce_msgids):
        if i % 20 == 0:
            print(f"  Progress: {i}/{len(bounce_msgids)}...")
        
        try:
            full_msg = pop.retr(msgnum)
            if b'check-hibernate' in full_msg.lower():
                headers_end = full_msg.find(b'\r\n\r\n')
                if headers_end > 0:
                    headers = full_msg[:headers_end].decode('utf-8', errors='replace')
                else:
                    headers = full_msg[:1000].decode('utf-8', errors='replace')
                
                subject = ""
                sender = ""
                for line in headers.split('\n'):
                    if line.lower().startswith('subject:'):
                        subject = line[8:].strip()
                    elif line.lower().startswith('from:'):
                        sender = line[5:].strip()
                
                cron_bounces.append((msgnum, "bounce-cron", f"{sender} - {subject[:50]}"))
        except Exception as e:
            pass
    
    return cron_bounces


def display_results(direct: List, bounces: List):
    """Display found emails for user review."""
    total = len(direct) + len(bounces)
    
    if total == 0:
        print("\n✓ No cron error emails found!")
        return
    
    print(f"\n{'='*70}")
    print(f"FOUND {total} CRON ERROR EMAILS")
    print(f"{'='*70}\n")
    
    if direct:
        print(f"Direct cron daemon messages ({len(direct)}):")
        for msgnum, etype, desc in direct[:10]:
            print(f"  #{msgnum:4d} - {desc}")
        if len(direct) > 10:
            print(f"  ... and {len(direct) - 10} more")
        print()
    
    if bounces:
        print(f"Bounce messages mentioning check-hibernate ({len(bounces)}):")
        for msgnum, etype, desc in bounces[:10]:
            print(f"  #{msgnum:4d} - {desc}")
        if len(bounces) > 10:
            print(f"  ... and {len(bounces) - 10} more")
        print()


def main():
    try:
        print("=" * 70)
        print("CRON EMAIL CLEANUP TOOL")
        print("=" * 70)
        
        # Get credentials
        print("\n1. Reading credentials...")
        login, account, secret = netrc.netrc().authenticators(MACHINE)
        client_id = account.split(":", 1)[1] if account and "MSAL:" in account else None
        if not client_id:
            raise RuntimeError("client_id not in ~/.netrc")
        
        # Get token
        print("2. Getting OAuth2 token...")
        token = get_access_token(client_id, secret)
        
        # Connect
        print("3. Connecting to hotmail via POP3...")
        pop = Pop3TLS(host=HOST, port=PORT)
        pop.connect()
        auth_xoauth2(pop, login, token)
        
        # Get total count
        total = pop.stat()
        print(f"   ✓ Connected. Total messages: {total}")
        
        # Scan for cron emails
        print("\n4. Scanning for cron errors...")
        direct, bounce_pending = scan_for_cron_emails(pop, total)
        
        # Check bounce emails
        print("\n5. Verifying bounce emails...")
        bounces = check_bounce_emails(pop, bounce_pending)
        
        # Display results
        display_results(direct, bounces)
        
        all_cron = direct + bounces
        if not all_cron:
            pop.quit()
            pop.close()
            return 0
        
        # Get confirmation
        print("\n" + "=" * 70)
        response = input(f"Delete these {len(all_cron)} emails? (type 'yes' to confirm): ").strip()
        
        if response != 'yes':
            print("Cancelled. No emails deleted.")
            pop.quit()
            pop.close()
            return 0
        
        # Delete
        print(f"\n6. Deleting {len(all_cron)} emails...")
        for msgnum, etype, desc in all_cron:
            pop.dele(msgnum)
        
        # Commit
        print("7. Committing deletions...")
        pop.quit()
        pop.close()
        
        print(f"\n✓ Successfully deleted {len(all_cron)} cron error emails!")
        return 0
        
    except Exception as e:
        print(f"\n✗ Error: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
