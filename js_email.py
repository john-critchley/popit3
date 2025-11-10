if __name__ != "__main__": print("Module:", __name__)
import re
from datetime import datetime
import html
from html.parser import HTMLParser
def parse_jobserve_email_part(html_part):
    """Parse a JobServe job suggestion email and extract structured fields."""
    assert isinstance(html_part, str), (
        f"parameter must be str, but got {type(html_part)}"
    )
    
    def _norm(s): 
        return re.sub(r"\s+", " ", html.unescape(s or "")).strip()
    
    class _Sniffer(HTMLParser):
        """Collect text with tag context to find specific elements."""
        def __init__(self):
            super().__init__(convert_charrefs=False)
            self.text = []
            self._stack = []
            self._current_tag = None
            self._current_attrs = {}
            self._capture = []
            
            # Structured data we're looking for
            self.job_title = None
            self.job_url = None
            self.h2_values = []  # Sequential h2 values after job title
            self.description_parts = []  # snippet and rest spans
            self.metadata_lines = []  # Employment Business, Ref, Posted
            
            self._in_heading = False
            self._in_h2 = False
            self._in_snippet = False
            self._in_rest = False
            self._in_metadata_td = False  # Track the TD container
            self._in_metadata_p = False   # Track the P inside it
            
        def handle_starttag(self, tag, attrs):
            self._stack.append(tag)
            self._current_tag = tag
            self._current_attrs = dict(attrs)
            
            # Check for metadata td container
            if tag == "td":
                style = self._current_attrs.get("style", "")
                if "border-bottom: 1px solid #7fd6f6" in style and "padding-top: 10px" in style:
                    self._in_metadata_td = True
            
            # Check for job title link
            if tag == "a":
                cls = self._current_attrs.get("class", "")
                if "heading" in cls:
                    self._in_heading = True
                    self._capture = []
                    # Extract the URL from the href attribute
                    self.job_url = self._current_attrs.get("href")
            
            # Check for h2 tags (location, salary, work_type)
            elif tag == "h2":
                self._in_h2 = True
                self._capture = []
            
            # Check for description spans
            elif tag == "span":
                cls = self._current_attrs.get("class", "")
                if "snippet" in cls:
                    self._in_snippet = True
                    self._capture = []
                elif "rest" in cls:
                    self._in_rest = True
                    self._capture = []
            
            # Check for paragraph inside metadata td
            elif tag == "p" and self._in_metadata_td:
                self._in_metadata_p = True
                self._capture = []
            
            # Handle br as newline in metadata
            elif tag == "br" and self._in_metadata_p:
                self._capture.append("\n")
        
        def handle_endtag(self, tag):
            if self._stack and self._stack[-1] == tag:
                self._stack.pop()
            
            if tag == "td" and self._in_metadata_td:
                self._in_metadata_td = False
            
            if tag == "a" and self._in_heading:
                self.job_title = _norm("".join(self._capture))
                self._in_heading = False
                self._capture = []
            
            elif tag == "h2" and self._in_h2:
                self.h2_values.append(_norm("".join(self._capture)))
                self._in_h2 = False
                self._capture = []
            
            elif tag == "span" and self._in_snippet:
                self.description_parts.append(_norm("".join(self._capture)))
                self._in_snippet = False
                self._capture = []
            
            elif tag == "span" and self._in_rest:
                self.description_parts.append(_norm("".join(self._capture)))
                self._in_rest = False
                self._capture = []
            
            elif tag == "p" and self._in_metadata_p:
                self.metadata_lines = [
                    line.strip() 
                    for line in "".join(self._capture).split("\n") 
                    if line.strip()
                ]
                self._in_metadata_p = False
                self._capture = []
        
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
    
    p = _Sniffer()
    p.feed(html_part or "")
    p.close()
    
    # Extract fields
    job_title = p.job_title
    job_url = p.job_url
    
    # Parse h2 values: location, [salary], work_type
    location = None
    salary = None
    work_type = None
    
    if len(p.h2_values) >= 1:
        location = p.h2_values[0] or None
    if len(p.h2_values) >= 2:
        salary = p.h2_values[1] or None
    if len(p.h2_values) >= 3:
        work_type = p.h2_values[2] or None
    
    # If middle h2 is empty, shift values
    if salary == "" and work_type:
        salary = None
        # work_type is already in the right place
    
    # Combine description parts (snippet + rest, filtering out "View on site" links)
    description_text = " ".join(p.description_parts)
    # Remove "View on site" and "... Show more" artifacts
    description_text = re.sub(r"\.\.\.\s*View on site$", "", description_text)
    description_text = re.sub(r"\.\.\.\s*Show more", "", description_text)
    
    # Parse metadata lines
    employment_business = None
    ref = None
    posted = None
    
    for line in p.metadata_lines:
        if line.startswith("Employment Business:") or line.startswith("Employment Agency:"):
            employment_business = line.split(":", 1)[1].strip()
        elif line.startswith("Ref:"):
            ref = line.split(":", 1)[1].strip()
        elif line.startswith("Posted:"):
            posted = line.split(":", 1)[1].strip()
    
    # Combine description with metadata
    description_parts = [description_text]
    if employment_business:
        description_parts.append(f"Employment Business: {employment_business}")
    if ref:
        description_parts.append(f"Ref: {ref}")
    if posted:
        description_parts.append(f"Posted: {posted}")
    
    description = "\n".join(description_parts)
    
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
