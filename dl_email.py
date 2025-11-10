import re, html
if __name__ != "__main__": print("Module:", __name__)
from datetime import datetime
from html.parser import HTMLParser

BOOKING_REF_RE = re.compile(r"\bDL-[A-Z0-9]+-[A-Z0-9]+(?:/\d+)?\b", re.I)
CANCEL_RE      = re.compile(r"\bcancel(?:led|lation|)\b", re.I)
BOOK_RE        = re.compile(r"\b(book(?:ing|ed)?|reserved|confirmation)\b", re.I)
UPDATE_RE      = re.compile(
    r"(?:\b(class|session|booking)\b.{0,40}\bhas been (?:changed|amended)\b)"
    r"|(?:\bprogramming change\b)"
    r"|(?:\breschedul(?:e|ed|ing)\b)"
    r"|(?:\bmoved\b)"
    , re.I
)
TIME_RANGE_RE  = re.compile(r"\b(\d{1,2}:\d{2})\s*-\s*(\d{1,2}:\d{2})\b", re.I)
SPORT_RE       = re.compile(r"\b(padel|pickleball|tennis|squash|badminton|table\s*tennis)\b", re.I)

def parse_david_lloyd_email_part(html_part: str) -> dict:
    assert isinstance(html_part, str), ("parameter must be str or derived from it.\n"
        f"However it is {type(html_part)}")
    def _norm(s): return re.sub(r"\s+", " ", html.unescape(s or "")).strip()
    def _key(s):  return re.sub(r"[^a-z0-9]+", "", (s or "").lower())
    def _has(a,b): 
        a,b=_key(a),_key(b); return bool(a and b and (a in b or b in a))

    def _parse_flex_date(s):
        if not s: return None
        t = re.sub(r"(\d{1,2})(st|nd|rd|th)", r"\1", s.strip())
        for fmt in ("%A %d %B %Y","%a %d %B %Y","%d %B %Y","%d %b %Y","%d/%m/%Y"):
            try: return datetime.strptime(t, fmt).date()
            except ValueError: pass
        return None

    def _parse_time_range(s):
        m = TIME_RANGE_RE.search(s or "")
        if not m: return (None, None)
        try:
            return (datetime.strptime(m.group(1), "%H:%M").time(),
                    datetime.strptime(m.group(2), "%H:%M").time())
        except ValueError:
            return (None, None)

    class _Sniffer(HTMLParser):
        """Collect visible text, kv pairs, and table rows. Skip struck-out text."""
        def __init__(self):
            super().__init__(convert_charrefs=False)
            self.text, self.rows, self.kv = [], [], {}
            self._stack, self._row, self._cell = [], [], []
            self._flag_stack, self._skip = [], 0
            self.saw_strike = False

        def handle_starttag(self, tag, attrs):
            style = next((v for k,v in attrs if k.lower()=="style"), "")
            flagged = tag.lower() in {"s","del","strike"} or ("line-through" in style.lower())
            self._flag_stack.append(flagged)
            if flagged: 
                self._skip += 1
                self.saw_strike = True

            self._stack.append(tag)
            if tag == "tr": self._row = []
            elif tag in ("td","th"): self._cell = []
            elif tag == "br" and self._cell is not None: self._cell.append("\n")

        def handle_endtag(self, tag):
            while self._stack:
                t = self._stack.pop()
                flagged = self._flag_stack.pop() if self._flag_stack else False
                if flagged: self._skip = max(0, self._skip-1)
                if t == tag: break

            if tag in ("td","th"):
                self._row.append(_norm("".join(self._cell))); self._cell = []
            elif tag == "tr":
                row = [c for c in (x.strip() for x in self._row) if c]
                if row:
                    self.rows.append(row)
                    if len(row)==2:
                        k,v=_norm(row[0]),_norm(row[1])
                        if k and v: self.kv[k]=v
                self._row=[]

        def handle_data(self, data):
            if not data or self._skip: return
            s = html.unescape(data)
            self.text.append(s)
            if self._cell is not None: self._cell.append(s)

        def handle_entityref(self, name): self.handle_data(f"&{name};")
        def handle_charref(self, name):  self.handle_data(f"&#{name};")

    p = _Sniffer(); p.feed(html_part or ""); p.close()
    full = _norm(" ".join(p.text))

    def kv(*labels):
        for k,v in p.kv.items():
            if any(_has(k, lab) for lab in labels): return v
        return None

    # kind: cancellation > update > booking > unknown
    if CANCEL_RE.search(full):
        kind = "cancellation"
    elif UPDATE_RE.search(full) or p.saw_strike:
        kind = "booking_update"
    elif BOOK_RE.search(full):
        kind = "booking"
    else:
        kind = "unknown"

    # booking ref (None if absent)
    m = BOOKING_REF_RE.search(full)
    booking_reference = kv("booking ref","booking reference","reference","ref") or (m.group(0) if m else None)

    club = kv("club","venue","location")

    # header mapping if class grid present
    wanted = {"time":("time",), "date":("date",), "day":("day",),
              "coach":("coach","coaches","instructor"),
              "venue":("venue","venues","location","club"),
              "session":("session","class","activity")}
    def map_header(row):
        m={}
        for i,c in enumerate(row):
            for k,vs in wanted.items():
                if k in m: continue
                if any(_has(c,v) for v in vs): m[k]=i
        return m if {"time","date"}<=set(m) else {}

    header=h_idx=None
    for i,r in enumerate(p.rows):
        m=map_header(r)
        if m: header,h_idx=m,i; break

    day = coach = venue = activity = None
    start = end = None

    if h_idx is not None:
        agg = {"time":None,"date":None,"day":None,"coach":None,"venue":None,"session":None}
        for r in p.rows[h_idx+1:h_idx+6]:
            def get(k):
                j = header.get(k)
                return (r[j].strip() if (j is not None and j < len(r) and r[j].strip()) else None)
            for k in list(agg):
                agg[k] = agg[k] or get(k)
            if agg["time"] and agg["date"] and (agg["coach"] or agg["venue"]):
                break

        d  = _parse_flex_date(agg["date"])
        t1,t2 = _parse_time_range(agg["time"] or "")
        if d and t1: start = datetime.combine(d, t1)
        if d and t2: end   = datetime.combine(d, t2)

        day   = agg["day"] or (d.strftime("%a") if d else None)
        coach = (agg["coach"].split("\n")[0].strip() if agg["coach"] else None)
        venue = agg["venue"]
        activity = kv("name","class","activity") or agg["session"]

    else:
        d  = _parse_flex_date(kv("date") or "")
        t1,t2 = _parse_time_range(kv("time") or "")
        if d and t1: start = datetime.combine(d, t1)
        if d and t2: end   = datetime.combine(d, t2)
        day = d.strftime("%a") if d else None

        court = kv("court")
        venue = court or kv("venue","venues","location") or None

        activity = kv("name","class","activity")
        if not activity:
            sm = SPORT_RE.search(full)
            activity = (sm.group(1).title() if sm else None)
        if not activity:
            activity = "Court" if "court" in full.lower() else ("Class" if "class" in full.lower() else None)

        raw_coach = kv("coach","coaches","instructor")
        coach = (raw_coach.split("\n")[0].strip() if raw_coach else None)

    return {
        "kind": kind,                       # now includes 'booking_update'
        "booking_reference": booking_reference,
        "activity": activity,
        "club": club,
        "venue": venue,
        "coach": coach,
        "day": day,
        "start": start,
        "end": end,
    }

