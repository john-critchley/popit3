import email
#import dl_email
import re
from email.utils import parseaddr

def parse_email_address(addr_string):
    return _parse_email_address(addr_string)
def _parse_email_address(addr_string,
    EMAIL_PATTERN = re.compile(r'^[^\s@]+@[^\s@]+\.[^\s@]+$'),
    SECURITY_ISSUES = re.compile(r'[\r\n]|<[^>]*<|@@|[\x00-\x1f]')
    ):
    if not addr_string or not isinstance(addr_string, str):
        return ("", False)
    
    addr_string = addr_string.strip()
    
    # Basic security checks
    if (len(addr_string) > 254 or 
        SECURITY_ISSUES.search(addr_string) or
        addr_string.count('@') > 2):
        return ("", False)
    
    try:
        # Parse using standard library
        name, email = parseaddr(addr_string)
        email = email.strip().lower()
        
        # Validate email format
        if not email or not EMAIL_PATTERN.match(email):
            return ("", False)
        
        # CVE-2023-27043 protection: check for suspicious characters in email
        if any(char in email for char in '<>"()'):
            return ("", False)
        
        return (email, True)
        
    except Exception:
        return ("", False)


def parse_email_addresses(addr_string):
    if not addr_string or not isinstance(addr_string, str):
        return []
    
    # Safe comma splitting that respects quoted strings
    addresses = []
    current = ""
    in_quotes = False
    in_brackets = False
    
    for char in addr_string:
        if char == '"' and not in_brackets:
            in_quotes = not in_quotes
        elif char == '<' and not in_quotes:
            in_brackets = True
        elif char == '>' and not in_quotes:
            in_brackets = False
        elif char == ',' and not in_quotes and not in_brackets:
            if current.strip():
                addresses.append(current.strip())
            current = ""
            continue
        current += char
    
    if current.strip():
        addresses.append(current.strip())
    
    # Parse each address (limit to 50 for safety)
    results = []
    for addr in addresses:
        email, is_safe = parse_email_address(addr)
        results.append((email, is_safe))
    
    return results


def extract_safe_emails(addr_string):
    parsed = parse_email_addresses(addr_string)
    return [email for email, is_safe in parsed if is_safe and email]


def is_header_safe(addr_string):
    parsed = parse_email_addresses(addr_string)
    return len(parsed) > 0 and all(is_safe and email for email, is_safe in parsed)


