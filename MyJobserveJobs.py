
#"MyJobserveJobs.py"
import gdata
import os
#import sys
import email
#import email.parser
#import dl_email
#import box
#import pandas as pd
#import numpy as np
import datetime
#import html
#import zoneinfo
import io
#import requests
import json
import zlib

import js_email

home=os.environ['HOME']
host='webdav.critchley.biz'
loc='.mail'

def uidl_encode(uid): 
    assert isinstance(uid, int), f"Should be a number but is {type(uid)}"
    return str(uid).encode('ascii') # Well it is a number so ascii will cover it
def uidl_decode(uid):
    return int(uid) # will raise something sensible (ValueError) if not valid

class JobserveProcessor:
    def __init__(self, webdav_client=None):
        self.dav=webdav_client
        self.gd=gdata.gdata(os.path.expanduser(f"~/.{self.__class__.__name__}.gdbm"))
    def process_js_mails(self, segregated_js_emails):
        now=datetime.datetime.now(datetime.timezone.utc)
        cleanup=[]

        if self.dav is not None:
            required_subdirs={'new', 'cur', 'tmp'}
            existing=self.dav.ls('/', detail=False)
            existing_dirs = {p.rstrip('/').split('/')[-1] for p in existing}
            for d in required_subdirs-existing_dirs:
                self.dav.mkdir('/'+d)
            existing={p.split('/')[-1] for p in self.dav.ls('/new', detail=False)}

        for uidl,msg in segregated_js_emails:
            #pdb.set_trace()

            msg_id=msg['Message-ID']
            print('Processing:', msg_id)
            print('Date', msg['Date']) # .strftime("%a %d %b %Y %H:%M")
            sent_date=email.utils.parsedate_to_datetime(msg['Date'])
            sent_date = (
                sent_date.replace(tzinfo=datetime.timezone.utc)
            if
                sent_date.tzinfo is None
            else
                sent_date.astimezone(datetime.timezone.utc)
            )
            mod_timestamp = sent_date.timestamp()
            print(sent_date)
            subject = msg.get('Subject', '')
            print(subject)
            if self.dav is not None:
                filename=f'''{zlib.crc32(f"{msg_id}{uidl}{sent_date}{subject}"
                            .encode("utf-8"))}.eml'''
                if filename not in self.gd:
                    remote_path = f"/new/{filename}" 
                    file_obj = io.BytesIO(msg.as_bytes())
                    self.dav.upload_fileobj(file_obj, remote_path, overwrite=True)
                    self.gd[filename]=True

            if (now - sent_date )> datetime.timedelta(days=10):
                cleanup.append(uidl)

            for part in msg.walk():    
                if part.is_multipart():
                    continue
                #print(part.get_content_type() )
                if(part.get_content_type()=="text/html"):
                    fn='.'.join([msg[h] for h in ['Subject', 'Message-ID']]+[str(uidl),'html'])
                    fn='html'+os.sep+'_'.join(fn.split(os.sep))
                    payload=(part.get_payload(decode=True))
                    print("Save to:", fn)
                    with open(fn, 'wb') as fd:
                        fd.write(payload)
                    os.utime(fn, (mod_timestamp, mod_timestamp))

                    # Skip emails that aren't job suggestions
                    subject = msg.get('Subject', '')
                    if 'job suggestion' not in subject:
                        print(f"Skipping non-job-suggestion email: {msg['Subject']}")
                        continue

                    charset = part.get_content_charset() or 'utf-8'
                    html_content = payload.decode(charset)
    #                print(html_content)


                    # Parse the JobServe email
                    parsed_job = js_email.parse_jobserve_email_part(html_content)
                    
                    # Save parsed data to file
                    base_fn = '.'.join([msg[h] for h in ['Subject', 'Message-ID']]+[str(uidl)])
                    base_fn = '_'.join(base_fn.split(os.sep))
                    parsed_fn = 'parsed' + os.sep + base_fn + '.json'
                    
                    # Ensure parsed directory exists
                    os.makedirs('parsed', exist_ok=True)
                    
                    print("Save parsed to:", parsed_fn)
                    with open(parsed_fn, 'w', encoding='utf-8') as fd:
                        json.dump(parsed_job, fd, indent=2, ensure_ascii=False)

                    
                    os.utime(parsed_fn, (mod_timestamp, mod_timestamp))

    #  [x.get_payload() for x in msg.walk() if not x.is_multipart() if x.get_content_type()== 'text/html']
    #                dle=dl_email.parse_david_lloyd_email_part(part.get_payload())
    #                all.append(box.Box({
    #                    'msg_id':msg_id, 'UIDL': uidl, 
    #                    'Sent': email.utils.parsedate_to_datetime(msg['Date']), **dle}))

    #    with gdata.gdata(os.sep.join([home, loc, '.jobs.gdbm'])) as booking_map:
        return list()
