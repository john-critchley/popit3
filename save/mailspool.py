
if __name__ != "__main__": print("Module:", __name__)
#"mailspool.py"
import zlib
import email
from email import policy
from pathlib import Path
#import webdav4
import traceback
import io

class MailSpool:
    dirstructure = {'new', 'cur', 'tmp'}
    def __init__(self, maildir_path, webdav_client=None, delete=True):
        self.maildir_path = Path(maildir_path)
        self.webdav_client = webdav_client
        self.delete=delete
        
        # Create local maildir structure
        for subdir in self.dirstructure:
            (self.maildir_path / subdir).mkdir(parents=True, exist_ok=True)
        
        # Create WebDAV maildir structure if client provided
        if self.webdav_client:
            self._ensure_webdav_structure()
    
    def store_messages(self, messages):
        """Store messages and return UIDLs of successfully stored messages"""
        successful_uidls = []
        
        for msg_data in messages:
            uidl, parsed_email = msg_data  # It's already a parsed Message object
            
            filename = self._generate_filename(parsed_email, uidl)

            raw_email_bytes = parsed_email.as_bytes(policy=getattr(parsed_email, "policy", policy.default))
            
            # Store locally (if maildir_path is set)
            if self.maildir_path:
                self._store_local(filename, raw_email_bytes)
            
            # Store via WebDAV (if webdav_client is set)
            if self.webdav_client:
                if self.maildir_path:
                    # Use local file if we wrote it
                    self._store_webdav_from_file(filename)
                else:
                    # Upload from memory if no local storage
                    self._store_webdav_from_memory(filename, raw_email_bytes)
            
            if self.delete:
                successful_uidls.append(uidl)
        
        return successful_uidls
    
    def _generate_filename(self, parsed_email, uidl):
        """Generate deterministic filename using CRC32"""
        message_id = parsed_email.get('Message-ID', '')
        date = parsed_email.get('Date', '')
        subject = parsed_email.get('Subject', '')
        
        hash_input = f"{message_id}{uidl}{date}{subject}".encode('utf-8')
        crc = zlib.crc32(hash_input) & 0xffffffff  # Ensure positive
        
        return f"{crc:08x}.eml"
    
    def _ensure_webdav_structure(self):
        """Create maildir structure on WebDAV server"""
        required_subdirs = self.dirstructure
        
        # Get existing directories with a single request (with retry)
        existing = self._webdav_with_retry(lambda: self.webdav_client.ls('/', detail=False))
        existing_dirs = {item.rstrip('/') for item in existing}
        
        # Only create missing directories
        missing_dirs = required_subdirs - existing_dirs
        
        for subdir in missing_dirs:
            print(f"Creating WebDAV directory: {subdir}")
            self._webdav_with_retry(lambda: self.webdav_client.mkdir(subdir))
            print(f"Successfully created: {subdir}")
    
    def _webdav_with_retry(self, operation, max_retries=3):
        """Execute WebDAV operation with retry logic"""
        import time
        for attempt in range(max_retries):
            try:
                return operation()
            except (ConnectionError, TimeoutError, OSError) as e:
                if attempt < max_retries - 1:
                    print(f"WebDAV operation attempt {attempt + 1} failed: {e}")
                    print(f"Retrying in {1 + attempt} seconds...")
                    time.sleep(1 + attempt)  # 1s, 2s, 3s
                else:
                    raise
    
    def _store_local(self, filename, raw_email_bytes):
        """Store email locally using maildir format"""
        if not self.maildir_path:
            return
            
        filepath = self.maildir_path / 'new' / filename
        tmp_filepath = self.maildir_path / 'tmp' / filename

        with open(tmp_filepath, 'wb') as f:
            f.write(raw_email_bytes)
        
        # Atomic move from tmp to new
        tmp_filepath.rename(filepath)
    
    def _store_webdav_from_file(self, filename):
        """Store email via WebDAV using existing local file"""
        local_filepath = self.maildir_path / 'new' / filename
        # Since webdav base URL already includes the Mail path, just use the relative path
        remote_path = f"new/{filename}"
        self._webdav_with_retry(lambda: self.webdav_client.upload_file(str(local_filepath), remote_path, overwrite=True))
    
    def _store_webdav_from_memory(self, filename, raw_email_bytes):
        """Store email via WebDAV from memory (no local file)"""
        remote_path = f"new/{filename}"  # Just the relative path
        file_obj = io.BytesIO(raw_email_bytes)
        self._webdav_with_retry(lambda: self.webdav_client.upload_fileobj(file_obj, remote_path, overwrite=True))
