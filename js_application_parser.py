if __name__ != "__main__": print("Module:", __name__)
import re
import html
from html.parser import HTMLParser


def parse_jobserve_application_confirmation(html_part: str) -> dict:
    """Parse a JobServe application confirmation email and extract fields.
    
    Args:
        html_part: HTML content of the email
        
    Returns:
        dict with keys: job_title, location, work_type, description, 
                       reference, posted_by, contact_name, contact_email, contact_phone
    """
    assert isinstance(html_part, str), (
        f"parameter must be str, but got {type(html_part)}"
    )
    
    def _norm(s): 
        return re.sub(r"\s+", " ", html.unescape(s or "")).strip()
    
    class _ApplicationSniffer(HTMLParser):
        """Extract table cell contents in sequence."""
        def __init__(self):
            super().__init__(convert_charrefs=False)
            self.in_td = False
            self.td_text = []
            self.all_cells = []
            
        def handle_starttag(self, tag, attrs):
            if tag == 'td':
                self.in_td = True
                self.td_text = []
        
        def handle_endtag(self, tag):
            if tag == 'td' and self.in_td:
                text = ''.join(self.td_text).strip()
                if text:
                    self.all_cells.append(text)
                self.in_td = False
        
        def handle_data(self, data):
            if self.in_td:
                self.td_text.append(data)
    
    parser = _ApplicationSniffer()
    parser.feed(html_part or "")
    parser.close()
    
    # Clean all cells
    cells = [_norm(c) for c in parser.all_cells]
    
    # Initialize result
    result = {
        'job_title': None,
        'location': None,
        'work_type': None,
        'description': None,
        'reference': None,
        'posted_by': None,
        'contact_name': None,
        'contact_email': None,
        'contact_phone': None,
    }
    
    # Pattern-based extraction with fallback to sequential parsing
    # The structure is fairly consistent:
    # - First few cells: confirmation message
    # - Job title, location, work_type, description appear in sequence
    # - Then labeled pairs: Reference: value, Posted By: value, etc.
    
    # Find reference number (distinctive pattern)
    for i, cell in enumerate(cells):
        if cell.lower() == 'reference:' and i + 1 < len(cells):
            result['reference'] = cells[i + 1]
        elif cell.lower() == 'posted by:' and i + 1 < len(cells):
            result['posted_by'] = cells[i + 1]
        elif cell.lower() == 'contact:' and i + 1 < len(cells):
            result['contact_name'] = cells[i + 1]
        elif cell.lower() == 'telephone:' and i + 1 < len(cells):
            phone = cells[i + 1]
            # Sometimes phone field is empty and email label follows
            if phone.lower() != 'email:':
                result['contact_phone'] = phone
        elif cell.lower() == 'email:' and i + 1 < len(cells):
            email_val = cells[i + 1]
            # Skip if it's just another label
            if '@' in email_val:
                result['contact_email'] = email_val
    
    # Try to find job details section
    # Look for the confirmation message, then job details follow
    for i, cell in enumerate(cells):
        if 'applied for the job listed below' in cell.lower():
            # Next cells should be: job_title, location, work_type, description
            if i + 1 < len(cells):
                result['job_title'] = cells[i + 1]
            if i + 2 < len(cells):
                # Check if this looks like a location
                loc = cells[i + 2]
                if len(loc) < 50 and not loc.startswith('http'):
                    result['location'] = loc
            if i + 3 < len(cells):
                # Check if this looks like work type
                wt = cells[i + 3]
                if wt.lower() in ['contract', 'permanent', 'temporary', 'freelance']:
                    result['work_type'] = wt
            if i + 4 < len(cells):
                # Description is usually longer
                desc = cells[i + 4]
                if len(desc) > 30:
                    result['description'] = desc
            break
    
    return result


if __name__ == "__main__":
    # Test with sample file
    import sys
    
    if len(sys.argv) > 1:
        filepath = sys.argv[1]
    else:
        filepath = "/home/john/py/popit3/sample_app_confirmation.html"
    
    try:
        with open(filepath, 'r') as f:
            html_content = f.read()
        
        result = parse_jobserve_application_confirmation(html_content)
        
        print("Parsed Application Confirmation:")
        for key, value in result.items():
            print(f"  {key:20s}: {value}")
    except FileNotFoundError:
        print(f"File not found: {filepath}")
        print("Usage: python3 js_application_parser.py [html_file]")
