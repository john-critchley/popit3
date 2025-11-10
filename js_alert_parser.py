import re
if __name__!="__main__": print("Module:", __name__)
from datetime import datetime
import html
from html.parser import HTMLParser


def parse_jobserve_alert(html_content):
    """Parse a JobServe job alert HTML file and extract structured fields.
    
    Args:
        html_content: String containing the HTML content of a JobServe alert email
        
    Returns:
        Dictionary with fields: job_title, location, salary, work_type, description,
        employment_business, ref, posted
    """
    assert isinstance(html_content, str), (
        f"parameter must be str, but got {type(html_content)}"
    )
    
    def _norm(s): 
        """Normalize whitespace and unescape HTML entities."""
        return re.sub(r"\s+", " ", html.unescape(s or "")).strip()
    
    class _AlertParser(HTMLParser):
        """Parse JobServe alert HTML to extract job details."""
        
        def __init__(self):
            super().__init__(convert_charrefs=False)
            self.text = []
            self._stack = []
            self._current_tag = None
            self._current_attrs = {}
            self._capture = []
            
            # Structured data we're extracting
            self.job_title = None
            self.job_url = None
            self.h2_values = []  # Location, salary, work_type
            self.description_text = None
            self.metadata = {}  # Employment Business/Agency/Company, Ref, Posted
            
            # State flags
            self._in_job_title = False
            self._in_h2 = False
            self._in_description_td = False
            self._in_metadata_td = False
            
            # Track depth for nested tags
            self._description_p_depth = 0
            
        def handle_starttag(self, tag, attrs):
            self._stack.append(tag)
            self._current_tag = tag
            self._current_attrs = dict(attrs)
            
            # Job title: <a class="heading" ...>
            if tag == "a":
                cls = self._current_attrs.get("class", "")
                if "heading" in cls:
                    self._in_job_title = True
                    self._capture = []
                    # Extract the URL from the href attribute
                    self.job_url = self._current_attrs.get("href")
            
            # H2 tags contain location, salary, work_type
            elif tag == "h2":
                style = self._current_attrs.get("style", "")
                if "font-size: 18px" in style:
                    self._in_h2 = True
                    self._capture = []
            
            # Track TD sections
            elif tag == "td":
                style = self._current_attrs.get("style", "")
                # Description TD: padding-top: 7px; padding-bottom: 20px
                if "padding-top: 7px" in style and "padding-bottom: 20px" in style:
                    self._in_description_td = True
                    self._capture = []
                # Metadata TD: padding-top: 10px; padding-bottom: 8px
                elif "padding-top: 10px" in style and "padding-bottom: 8px" in style:
                    # Only consider it metadata if we've already captured description
                    if self.description_text:
                        self._in_metadata_td = True
                        self._capture = []
            
            # Track P tag depth in description
            elif tag == "p" and self._in_description_td:
                self._description_p_depth += 1
            
            # Handle br tags as newlines
            elif tag == "br":
                if self._in_description_td or self._in_metadata_td:
                    self._capture.append("\n")
        
        def handle_endtag(self, tag):
            if self._stack and self._stack[-1] == tag:
                self._stack.pop()
            
            if tag == "td":
                if self._in_description_td:
                    # Capture the full description content
                    self.description_text = _norm("".join(self._capture))
                    self._in_description_td = False
                    self._description_p_depth = 0
                    self._capture = []
                elif self._in_metadata_td:
                    # Parse metadata lines
                    metadata_content = "".join(self._capture)
                    lines = [line.strip() for line in metadata_content.split("\n") if line.strip()]
                    
                    for line in lines:
                        # Skip email links
                        if not line or line.startswith("mailto:") or ("@" in line and ":" not in line):
                            continue
                        
                        # Parse key: value pairs
                        if ":" in line:
                            key, value = line.split(":", 1)
                            key = key.strip()
                            value = value.strip()
                            
                            if key in ["Employment Business", "Employment Agency", "Company"]:
                                self.metadata["employment_business"] = value
                            elif key == "Ref":
                                self.metadata["ref"] = value
                            elif key == "Posted":
                                self.metadata["posted"] = value
                    
                    self._in_metadata_td = False
                    self._capture = []
            
            elif tag == "a" and self._in_job_title:
                self.job_title = _norm("".join(self._capture))
                self._in_job_title = False
                self._capture = []
            
            elif tag == "h2" and self._in_h2:
                value = _norm("".join(self._capture))
                # Skip empty h2 values
                if value:
                    self.h2_values.append(value)
                self._in_h2 = False
                self._capture = []
            
            elif tag == "p" and self._in_description_td:
                self._description_p_depth = max(0, self._description_p_depth - 1)
        
        def handle_data(self, data):
            if not data:
                return
            s = html.unescape(data)
            self.text.append(s)
            if self._capture is not None:
                self._capture.append(s)
        
        def handle_entityref(self, name): 
            self.handle_data(f"&{name};")
        
        def handle_charref(self, name):  
            self.handle_data(f"&#{name};")
    
    # Parse the HTML
    parser = _AlertParser()
    parser.feed(html_content or "")
    parser.close()
    
    # Extract structured fields
    job_title = parser.job_title
    job_url = parser.job_url
    
    # Parse h2 values: location, [salary], work_type
    location = None
    salary = None
    work_type = None
    
    if len(parser.h2_values) >= 1:
        location = parser.h2_values[0]
    if len(parser.h2_values) >= 2:
        salary = parser.h2_values[1]
    if len(parser.h2_values) >= 3:
        work_type = parser.h2_values[2]
    
    # Get metadata
    employment_business = parser.metadata.get("employment_business")
    ref = parser.metadata.get("ref")
    posted = parser.metadata.get("posted")
    
    # Build complete description with metadata appended
    description_parts = []
    if parser.description_text:
        description_parts.append(parser.description_text)
    
    if employment_business:
        description_parts.append(f"Employment Business: {employment_business}")
    if ref:
        description_parts.append(f"Ref: {ref}")
    if posted:
        description_parts.append(f"Posted: {posted}")
    
    description = "\n".join(description_parts) if description_parts else None
    
    return {
        "job_title": job_title,
        "job_url": job_url,
        "location": location,
        "salary": salary,
        "work_type": work_type,
        "description": description,
        "employment_business": employment_business,
        "ref": ref,
        "posted": posted,
    }


if __name__ == "__main__":
    # Example usage
    import sys
    
    if len(sys.argv) > 1:
        # Read from file (try UTF-8 first, fallback to ISO-8859-1)
        try:
            with open(sys.argv[1], 'r', encoding='utf-8') as f:
                html_content = f.read()
        except UnicodeDecodeError:
            with open(sys.argv[1], 'r', encoding='iso-8859-1') as f:
                html_content = f.read()
        
        result = parse_jobserve_alert(html_content)
        
        print("Job Title:", result['job_title'])
        print("Job URL:", result['job_url'])
        print("Location:", result['location'])
        print("Salary:", result['salary'])
        print("Work Type:", result['work_type'])
        print("\nDescription:")
        print(result['description'])
        print("\n" + "="*80)
        print("Employment Business:", result['employment_business'])
        print("Ref:", result['ref'])
        print("Posted:", result['posted'])
    else:
        print("Usage: python js_alert_parser.py <html_file>")
