if __name__ != "__main__": print("Module:", __name__)
import io
import netrc
import zlib
from pathlib import Path

import webdav4.client


class MailSpool:
    """
    Store incoming raw emails to a local maildir and/or a WebDAV maildir.

    WebDAV credentials are read from ~/.netrc (same pattern as WebDAVDelivery
    in webdav_deliver.py).  Pass webdav_host + webdav_path to enable remote
    storage; omit them for local-only.

    Args:
        maildir_path: Local maildir root (new/cur/tmp created automatically).
        webdav_host:  WebDAV hostname, e.g. 'webdav.critchley.biz'.
        webdav_path:  Remote path, e.g. '/mail/john'.
        delete:       Return UIDLs so the caller can delete from POP3.
    """

    _SUBDIRS = ('new', 'cur', 'tmp')

    def __init__(self, maildir_path, webdav_host=None, webdav_path=None, delete=True):
        self.maildir_path = Path(maildir_path)
        self.delete = delete
        self._wdclient = None

        for subdir in self._SUBDIRS:
            (self.maildir_path / subdir).mkdir(parents=True, exist_ok=True)

        if webdav_host and webdav_path:
            user, _, password = netrc.netrc().authenticators(webdav_host)
            self._wdclient = webdav4.client.Client(
                f'https://{webdav_host}{webdav_path}', auth=(user, password)
            )
            self._ensure_webdav_dirs()

    def _ensure_webdav_dirs(self):
        try:
            existing = {item['name'].rstrip('/').split('/')[-1]
                        for item in self._wdclient.ls('.')}
        except Exception:
            existing = set()
        for subdir in self._SUBDIRS:
            if subdir not in existing:
                try:
                    self._wdclient.mkdir(subdir)
                except Exception:
                    pass

    def _filename(self, parsed_email, uidl):
        msg_id   = parsed_email.get('Message-ID', '')
        date     = parsed_email.get('Date', '')
        subject  = parsed_email.get('Subject', '')
        data     = f'{msg_id}{uidl}{date}{subject}'.encode('utf-8')
        crc      = zlib.crc32(data) & 0xffffffff
        return f'{crc:08x}.eml'

    def store_messages(self, messages):
        """Store messages; return UIDLs of stored messages if delete=True."""
        stored = []
        for uidl, parsed_email in messages:
            raw   = str(parsed_email)
            fname = self._filename(parsed_email, uidl)

            # local: write to tmp then rename (atomic)
            tmp = self.maildir_path / 'tmp' / fname
            dst = self.maildir_path / 'new' / fname
            tmp.write_text(raw, encoding='utf-8')
            tmp.rename(dst)

            # remote
            if self._wdclient:
                try:
                    self._wdclient.upload_fileobj(
                        io.BytesIO(raw.encode('utf-8')),
                        f'new/{fname}',
                        overwrite=True,
                    )
                except Exception as e:
                    print(f'WebDAV upload failed for {fname}: {e}')

            if self.delete:
                stored.append(uidl)

        return stored
