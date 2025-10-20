# WORK ON This
import os
import gdata
import email
import scanmailheaders

import MyDavidLloydSchedule
import MyJobserveJobs
import jobserve_parser
import mailspool

import json
import traceback

import netrc
import webdav4.client
import time
mode="n" # change to "n" for going from clean

host='webdav.critchley.biz' # needs to be parameterized better!
user, account, password=netrc.netrc().authenticators(host)

# Initialize WebDAV clients with retry logic for network glitches
def create_webdav_client_with_retry(url, auth, max_retries=3):
    for attempt in range(max_retries):
        try:
            client = webdav4.client.Client(url, auth=auth)
            # Test the connection
            client.ls('/', detail=False)
            return client
        except (ConnectionError, TimeoutError, OSError) as e:
            if attempt < max_retries - 1:
                print(f"WebDAV connection attempt {attempt + 1} failed: {e}")
                print(f"Retrying in {2 ** attempt} seconds...")
                time.sleep(2 ** attempt)  # Exponential backoff: 1s, 2s, 4s
            else:
                print(f"WebDAV connection failed after {max_retries} attempts: {e}")
                raise

webdav_client = create_webdav_client_with_retry(f'https://{host}/john/Mail', (user, password))
js_webdav_client = create_webdav_client_with_retry(f'https://{host}/js/Mail', (user, password))
# Create MailSpool instances for different email addresses
mail_spool = mailspool.MailSpool(os.path.expanduser('~/Mail'), webdav_client)
# Note - using webdav_client not js_webdav_client
# Keep the MyJobserveJobs processor available under a distinct name, but use the
# `jobserve_parser` module (the jobserve parser) for processing so it benefits
# from the new alert handling and gdbm storage logic.
myjobserve_processor = MyJobserveJobs.JobserveProcessor(webdav_client=webdav_client)

map= [
        ("john.ncaf@critchley.biz", lambda x: [ uidl for uidl, eb in x ]),
        ("john.bat@critchley.biz", lambda x: [ uidl for uidl, eb in x ]),
        ("john.guardian@critchley.biz", lambda x: [ uidl for uidl, eb in x ]),
        ("john.duolingo@critchley.biz", lambda x: [ uidl for uidl, eb in x ]),
        ("john.ig@critchley.biz", lambda x: [ uidl for uidl, eb in x ]),
        ("john.od@critchley.biz", lambda x: [ uidl for uidl, eb in x ]),
        ("readingreddit@critchley.biz", lambda x: [ uidl for uidl, eb in x ]),
        ("o_f@critchley.biz", lambda x: [ uidl for uidl, eb in x ]),
        ("john.dl@critchley.biz", MyDavidLloydSchedule.process_dl_mails),
#        ("john.js@critchley.biz", MyJobserveJobs.process_js_mails),
        ("john.js@critchley.biz", jobserve_parser.process_js_mails),
        ("john.amazon.com@critchley.biz", mail_spool.store_messages),
        ("john.tr@critchley.biz", mail_spool.store_messages),
        ("john.q@critchley.biz", mail_spool.store_messages),
    ]
def do_processing(new_emails, mail_db=None, meta_db_file = os.path.expanduser("~/.email3.meta.gdbm")):
    assert isinstance(meta_db_file, (str, bytes, os.PathLike)), f"meta_db_file, is a {type(meta_db_file)} not str, bytes or os.PathLike."
    foo={}
    deletes=[]
    print("Processing new emails:")
    print(*(x[0].decode('utf-8') for x in new_emails), sep=',')
    
    with gdata.gdata(gdbm_file=meta_db_file, mode=mode) as metadb:
        for uidl, email_bin in new_emails:
            msg=email.message_from_bytes(email_bin)
            To=msg['To']
            #print('To:', To)
            to_addresses=[ address for address, safe in scanmailheaders.parse_email_addresses(To) if bool(safe)]
            for addr in to_addresses:
                foo.setdefault(addr, []).append((uidl,msg))
    print(json.dumps(sorted([(to, len(refs)) for to, refs in foo.items()], key=lambda x:x[1])))
    for email_match, mail_func in map:
        print(f"Processing {email_match}:")
        try:
            deletes+=(mail_func(foo.get(email_match, []))) # still call even if new IDs, for old mail expiration etc
        except (OSError, ValueError, KeyError, ConnectionError, TimeoutError) as e:
            print(f"Error processing emails for {email_match}: {e}")
            print(traceback.format_exc())

    return deletes
#def main():
#    dbfile = os.path.expanduser("~/.email3.mail.gdbm")
#    with gdata.gdata_raw(gdbm_file=dbfile, mode="w") as maildb:
#        nmails=[(uidl, msg_bin) for uidl, msg_bin in maildb.items()]
#        print(do_processing(nmails))
#
#if __name__=='__main__':
#    main()
