if __name__ != "__main__": print("Module:", __name__)
import gdata
import os
import sys
import email
import email.parser
import dl_email
import box
import pandas as pd
import numpy as np
import datetime
import html
import zoneinfo
import netrc
import webdav4.client
import io
import requests

home=os.environ['HOME']
datetime_fileds=['start','end','Sent']
booking_reference="booking_reference"
host='webdav.critchley.biz'
loc='.mail'

def dd(x):
    return box.Box({k:v.isoformat() if k  in datetime_fileds and isinstance(v, datetime.datetime) else v for k,v in x.items() })
def td(x):
    return box.Box({k:datetime.datetime.fromisoformat(v) if k in datetime_fileds and isinstance(v, str) else v for k,v in x.items()})    

def aox(db, key, val, val2):
    "add new key/val list to db or extend existing one"
    # note db works differently to just a dict
    ovals=db.get(key, [])
    ovals_msg_ids=[v[0] for v in ovals]
    if val in ovals_msg_ids:
        return False
    db[key]=[*ovals, [val, val2]] # using lists or else json will anyway
    return True

def render_events_table_html(events, title="Upcoming events", tz="Europe/London", pretty=False):
    if isinstance(title, bool): pretty, title = title, "Upcoming events"
    elif isinstance(tz, bool): pretty, tz = tz, "Europe/London"

    tzinfo = zoneinfo.ZoneInfo(tz)
    rows   = [dict(e) for e in events]
    keys   = list(rows[0]) if rows else []
    loc    = lambda dt: (dt if dt.tzinfo else dt.replace(tzinfo=tzinfo)).astimezone(tzinfo)

    if rows:
        last = datetime.datetime.max.replace(tzinfo=tzinfo)
        rows.sort(key=lambda r: loc(r.get("start")) if r.get("start") else last)

    safe = lambda k: "".join(ch.lower() if ch.isalnum() else "-" for ch in str(k))
    nl   = "\n" if pretty else ""
    ind  = (lambda n: "  "*n) if pretty else (lambda n: "")

    # Mark columns once for easy CSS targeting
    colgroup = f"{ind(1)}<colgroup>{nl}" + f"{nl}".join(
        f'{ind(2)}<col class="c-{safe(k)}">' for k in keys
    ) + f"{nl}{ind(1)}</colgroup>{nl}"

    thead = f"{ind(1)}<thead>{nl}{ind(2)}<tr>{nl}{ind(3)}" + f"{nl}{ind(3)}".join(
        f'<th class="c-{safe(k)}" scope="col">{html.escape(str(k))}</th>' for k in keys
    ) + f"{nl}{ind(2)}</tr>{nl}{ind(1)}</thead>{nl}"

    body = []
    for r in rows:
        cells = []
        for k in keys:
            v = r.get(k, "")
            if k in ("start","end","Sent") and v:
                v = loc(v).strftime("%a %d %b %Y %H:%M")
            cells.append(f'<td class="c-{safe(k)}">{html.escape(str(v))}</td>')
        body.append(f"{ind(2)}<tr>{nl}{ind(3)}" + f"{nl}{ind(3)}".join(cells) + f"{nl}{ind(2)}</tr>")
    if not body:
        body = [f'{ind(2)}<tr><td class="c-empty">No events</td></tr>']

    return (
        (f"{nl}<!-- bookings table -->{nl}" if pretty else "")
        + f"<table class=\"bks\">{nl}"
        + colgroup
        + f"{ind(1)}<caption>{html.escape(title)}</caption>{nl}"
        + thead
        + f"{ind(1)}<tbody>{nl}" + f"{nl}".join(body) + f"{nl}{ind(1)}</tbody>{nl}"
        + "</table>"
    )

def uidl_encode(uid): 
    assert isinstance(uid, int), f"Should be a number but is {type(uid)}."
    return str(uid).encode('ascii') # Well it is a number so ascii will cover it
def uidl_decode(uid):
    return int(uid) # will raise something sensible (ValueError) if not valid

def process_dl_mails(segregated_dl_emails):
    #keys=None
    verbose=False
    all=[]
    now=datetime.datetime.now()
    cleanup=[]

    for uidl,msg in segregated_dl_emails:
        msg_id=msg['Message-ID']
        for part in msg.walk():    
            if part.is_multipart():
                continue
            #print(part.get_content_type() )
            if(part.get_content_type()=="text/html"):
###  [x.get_payload() for x in msg.walk() if not x.is_multipart() if x.get_content_type()== 'text/html']
                dle=dl_email.parse_david_lloyd_email_part(part.get_payload())
                all.append(box.Box({
                    'msg_id':msg_id, 'UIDL': uidl, 
                    'Sent': email.utils.parsedate_to_datetime(msg['Date']), **dle}))

    with gdata.gdata(os.sep.join([home, loc, '.booking_map2.gdbm'])) as booking_map:
        with gdata.gdata_simple(os.sep.join([home, loc, '.booksings_db2.gdbm'])) as mail_dbm:
            for bo in sorted(all, key=lambda k:k['Sent']):
                assert bo.kind in ['booking', 'cancellation', "booking_update"], "not valid kind: "+bo.kind
                if any(bo[x] is None for x in [booking_reference, "start", "end"]):
                    print(chr(8227), int(bo.UIDL), "has None field:")
                    print(bo)
                    continue
                if bo.end<now:
                    print(chr(8226), bo['start'], bo['end'], bo[booking_reference], bo['msg_id'])
                    cleanup.append(bo)
                if not aox(booking_map, bo[booking_reference], bo.msg_id, uidl_decode(bo.UIDL)):
                    if 'verbose' in vars() and bool(verbose) and verbose:
                        print('Skipping', bo[booking_reference], bo.msg_id, "because already processed")
                    continue
                
                # State check: booking should NOT exist yet; cancellation/update should exist
                if bo.kind == 'booking':
                    if bo[booking_reference] in mail_dbm:
                        # Booking already exists - likely duplicate confirmation email
                        print(f'Warning: {bo.msg_id}, {bo[booking_reference]}: duplicate booking email (already exists)')
                        continue
                elif bo.kind in ('cancellation', 'booking_update'):
                    if bo[booking_reference] not in mail_dbm:
                        # Cancellation/update for booking that's not in DB
                        # Likely already expired and cleaned up, or cancel→book→cancel sequence
                        # Skip silently
                        continue
                
                if bo.kind=='booking':
                    required_fields=['day', 'activity', 'coach', 'start', 'end',  'venue', 'club']
                    
                    mail_dbm[bo[booking_reference]]=dd({k:bo[k] for k in required_fields if k in bo}).to_json()
                elif bo.kind=='cancellation':
                    del mail_dbm[bo[booking_reference]]
                elif bo.kind=='booking_update':
                    # Update existing booking with new details
                    required_fields=['day', 'activity', 'coach', 'start', 'end',  'venue', 'club']
                    mail_dbm[bo[booking_reference]]=dd({k:bo[k] for k in required_fields if k in bo}).to_json()

    with gdata.gdata_simple(os.sep.join([home, loc, '.booksings_db2.gdbm']), mode='r') as db:
        df=pd.DataFrame(([td(box.Box({booking_reference:k, **box.Box.from_json(v)})) for k,v in db.items()]))

    df1=df[df.end>=now].sort_values('start')
#    def rfc2822_gmt(dt= None):
#        return email.utils.format_datetime(
#              now + datetime.timedelta(minutes=15)
#            if dt is None else
#                dt.replace(tzinfo=datetime.timezone.utc)
#              if dt.tzinfo is None else
#                dt.astimezone(datetime.timezone.utc),
#            usegmt=True
#        )

    bookings_html=(
        '<!DOCTYPE html>\n'
        '<html><head><title>David Lloyd Bookings</title>'
        f"""<style>
.bks{{font-family:system-ui,-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;border-collapse:collapse;width:100%}}
.bks th,.bks td{{border:1px solid #ddd;padding:8px;text-align:center}}
.bks tr:nth-child(even){{background:#f9f9f9}}
.bks th{{background:#222;color:#fff}}
.bks caption{{text-align:left;font-weight:600;padding:8px 0;font-size:1.05rem}}
.bks .c-booking-reference{{font-size: smaller;}}
</style>"""
        #f'<meta http-equiv="expires" content="{rfc2822_gmt()}">'
        '</head>\n'
        f'<body><h1>David Lloyd Bookings</h1>\n'
        f'<p>{render_events_table_html(df1.to_dict("records"), title="My bookings")}</p>\n'
        f'<p><em>{now.strftime('%Y/%m/%d %H:%M:%S')}</em><p>\n'
        '</body></html>'
        )

    user, account, password=netrc.netrc().authenticators(host)

    client=webdav4.client.Client(f'https://{host}', auth=(user,password))
    file_loc='DavidLloyd/timetable.html'
    deploy_url='https://www.critchley.biz/deploy/'+file_loc

    html_bytesio = io.BytesIO(bookings_html.encode('utf-8'))
    html_bytesio.seek(0)
    client.upload_fileobj(html_bytesio, f"staging/{file_loc}", overwrite=True)

    resp=requests.get(deploy_url)
    print('Deployed:', resp.ok)
    df1=df[df.end<now].sort_values('start')
    booking_refs={x[booking_reference] for x in cleanup}
    booking_info=[]
    with gdata.gdata(os.sep.join([home, loc, '.booking_map2.gdbm'])) as booking_map:
        for i in booking_refs:
            booking_info+=booking_map[i] 
            del booking_map[i]
    #uuid_set={str(i[1]) for i in booking_info}
    uuid_set={uidl_encode(i[1]) for i in booking_info}
    msg_id_set={i[0] for i in booking_info}
    with gdata.gdata_simple(os.sep.join([home, loc, '.booksings_db2.gdbm']), mode='w') as db:
        for msg_id in msg_id_set:
            if msg_id in db:
                del db[msg_id]
    return list(uuid_set)
