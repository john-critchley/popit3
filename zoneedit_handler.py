if __name__ != "__main__": print("Module:", __name__)

"""
Handler for ZoneEdit 2FA access-token emails arriving at jsr_critchley@hotmail.com.

Filters by: From support@zoneedit.com + subject contains "[ZoneEdit] Access token".
Extracts the 6-digit token and writes it to ~/.zoneedit_token (mode 0600).
Token expires in 5 minutes so the file is stamped with received time.
"""

import email.header
import email.utils
import re
import datetime
import os

TOKEN_FILE = os.path.expanduser('~/.zoneedit_token')
SENDER     = 'support@zoneedit.com'
SUBJECT_RE = re.compile(r'\[ZoneEdit\].*access token', re.IGNORECASE)
TOKEN_RE   = re.compile(r'Access Token:\s*(\d+)', re.IGNORECASE)


def _decode_header(h):
    if not h:
        return ''
    parts = email.header.decode_header(h)
    out = []
    for part, charset in parts:
        if isinstance(part, bytes):
            out.append(part.decode(charset or 'utf-8', errors='replace'))
        else:
            out.append(part)
    return ''.join(out)


def _get_body(msg):
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == 'text/plain':
                payload = part.get_payload(decode=True)
                if payload:
                    return payload.decode(part.get_content_charset() or 'utf-8', errors='replace')
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            return payload.decode(msg.get_content_charset() or 'utf-8', errors='replace')
    return ''


def process_zoneedit_mails(emails):
    """
    Called by process_emails.py with all emails to jsr_critchley@hotmail.com.
    Filters to ZoneEdit token emails, writes token to ~/.zoneedit_token, deletes those emails.
    Non-ZoneEdit emails are left untouched (not returned in delete set).
    """
    if not emails:
        return set()

    delete = set()

    for uidl, msg in emails:
        frm     = _decode_header(msg.get('From', ''))
        subject = _decode_header(msg.get('Subject', ''))

        if SENDER not in frm or not SUBJECT_RE.search(subject):
            continue

        body  = _get_body(msg)
        match = TOKEN_RE.search(body)
        if not match:
            print(f'  ZoneEdit: token email found but could not extract token (subject: {subject!r})')
            continue

        token = match.group(1)
        try:
            received = email.utils.parsedate_to_datetime(msg.get('Date', '')).isoformat()
        except Exception:
            received = datetime.datetime.utcnow().isoformat()

        try:
            fd = os.open(TOKEN_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, 'w') as f:
                f.write(f'{token}\n{received}\n')
            print(f'  ZoneEdit: token {token!r} written to {TOKEN_FILE} (received {received})')
            delete.add(uidl)
        except Exception as e:
            print(f'  ZoneEdit: file write failed ({e}) — leaving in spool for retry')

    return delete
