#!/usr/bin/env python3
"""
WebDAV email delivery for Envoy.

Delivers outbound emails by writing .eml files to a WebDAV maildir,
bypassing SMTP entirely. Used for recipients whose mail servers
block direct SMTP from this host.
"""

import io
import netrc
import time
import zlib
from email.message import EmailMessage
from email.utils import formatdate, make_msgid

import webdav4.client


class WebDAVDelivery:
    """
    Delivers emails to a WebDAV maildir.

    Usage:
        delivery = WebDAVDelivery('webdav.critchley.biz', '/mail/john')
        delivery.deliver(to, subject, body, from_addr, in_reply_to)
    """

    def __init__(self, host: str, path: str):
        """
        Connect to WebDAV and ensure maildir structure exists.

        Args:
            host: WebDAV hostname (credentials from ~/.netrc)
            path: WebDAV path to maildir root (e.g. '/mail/john')
        """
        user, _, password = netrc.netrc().authenticators(host)
        self.client = webdav4.client.Client(
            f'https://{host}{path}', auth=(user, password)
        )
        # Ensure maildir structure — list once, only mkdir what's missing
        try:
            existing = {item['name'].rstrip('/').split('/')[-1]
                        for item in self.client.ls('.')}
        except Exception:
            existing = set()
        for subdir in ('new', 'cur', 'tmp'):
            if subdir not in existing:
                try:
                    self.client.mkdir(subdir)
                except Exception:
                    pass

    def deliver(self, to: str, subject: str, body: str,
                from_addr: str = 'Envoy <envoy@critchley.biz>',
                in_reply_to: str = None) -> bytes:
        """
        Construct and deliver an email to the WebDAV maildir.

        Args:
            to: Recipient address
            subject: Email subject
            body: Plain text body
            from_addr: Sender address
            in_reply_to: Optional Message-ID for threading

        Returns:
            Raw message bytes
        """
        msg = EmailMessage()
        msg['From'] = from_addr
        msg['To'] = to
        msg['Subject'] = subject
        msg['Date'] = formatdate(localtime=True)
        msg['Message-ID'] = make_msgid(domain='critchley.biz')
        msg['MIME-Version'] = '1.0'
        if in_reply_to:
            msg['In-Reply-To'] = in_reply_to
        msg.set_content(body)

        filename = self._make_filename(msg)
        raw = msg.as_bytes()
        self.client.upload_fileobj(io.BytesIO(raw), f'new/{filename}')
        return raw

    def _make_filename(self, msg: EmailMessage) -> str:
        """
        Generate a unique filename for the delivered email.

        Uses 'E' prefix to distinguish from popit3 CRC32 filenames (8 hex chars).
        Format: E-<timestamp_us>-<crc8>.eml
        """
        timestamp_us = int(time.time() * 1_000_000)
        # CRC of subject+to for extra uniqueness
        extra = f"{msg['Subject']}{msg['To']}".encode('utf-8')
        crc = zlib.crc32(extra) & 0xffffffff
        return f"E-{timestamp_us}-{crc:08x}.eml"
