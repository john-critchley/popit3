if __name__ != "__main__": print("Module:", __name__)
# WORK ON This
import os
import gdata
import email
import scanmailheaders

import MyDavidLloydSchedule
## import MyJobserveJobs
##import jobserve_parser
## import mailspool  # re-enable when other handlers are restored

import json
import traceback

## import netrc        # re-enable with webdav clients
## import webdav4.client
## import time
## import httpx

mode="w" # change to "n" for going from clean

## host='webdav.critchley.biz'
## user, account, password=netrc.netrc().authenticators(host)

def _norm(v): # skip crap unicode identifier which we now get
    i=0
    while i<len(v) and int(v[i])>0x7f:
        i+=1
    return v[i:]

## def create_webdav_client_with_retry(url, auth, max_retries=3):
##     for attempt in range(max_retries):
##         try:
##             client = webdav4.client.Client(url, auth=auth)
##             client.ls('/', detail=False)
##             return client
##         except (ConnectionError, TimeoutError, OSError, httpx.ConnectTimeout) as e:
##             if attempt < max_retries - 1:
##                 print(f"WebDAV connection attempt {attempt + 1} failed: {e}")
##                 print(f"Retrying in {2 ** attempt} seconds...")
##                 time.sleep(2 ** attempt)
##             else:
##                 print(f"WebDAV connection failed after {max_retries} attempts: {e}")
##                 raise

## webdav_client = create_webdav_client_with_retry(f'https://{host}/mail/john', (user, password))
## js_webdav_client = create_webdav_client_with_retry(f'https://{host}/mail/john.js', (user, password))
## mail_spool = mailspool.MailSpool(os.path.expanduser('~/Mail'), webdav_client)
## js_mail_spool = mailspool.MailSpool(os.path.expanduser('~/py/popit3/jsMail'), js_webdav_client, delete=False)
## reddit_mail_spool = mailspool.MailSpool(os.path.expanduser('~/.reddit_mail'), delete=False)
## wf_mail_spool = mailspool.MailSpool(os.path.expanduser('~/py/popit3/wfMail'), webdav_client, delete=False)
## envoy_webdav_client = create_webdav_client_with_retry(f'https://{host}/mail/envoy', (user, password))
## envoy_mail_spool = mailspool.MailSpool(os.path.expanduser('~/py/envoy/requests'), envoy_webdav_client, delete=True)
## envoy_responses_mail_spool = mailspool.MailSpool(os.path.expanduser('~/py/envoy/responses'), delete=True)
## import newparser_jobserve

map= [
        # Disabled while restarting popit — DL only
        #("john.flix@critchley.biz", lambda x: [ uidl for uidl, eb in x ]),
        #("john.ncaf@critchley.biz", lambda x: [ uidl for uidl, eb in x ]),
        #("john.bat@critchley.biz", lambda x: [ uidl for uidl, eb in x ]),
        #("john.guardian@critchley.biz", lambda x: [ uidl for uidl, eb in x ]),
        #("john.duolingo@critchley.biz", lambda x: [ uidl for uidl, eb in x ]),
        #("john.ig@critchley.biz", lambda x: [ uidl for uidl, eb in x ]),
        #("john.od@critchley.biz", lambda x: [ uidl for uidl, eb in x ]),
        #("readingreddit@critchley.biz", reddit_mail_spool.store_messages),
        #("o_f@critchley.biz", lambda x: [ uidl for uidl, eb in x ]),
        ("john.dl@critchley.biz", MyDavidLloydSchedule.process_dl_mails),
#        ("john.js@critchley.biz", MyJobserveJobs.process_js_mails),
###        ("john.js@critchley.biz", jobserve_parser.process_js_mails),
        #("john.js@critchley.biz", newparser_jobserve.process_js_mails),
#        ("john.js@critchley.biz", js_mail_spool.store_messages),
        #("envoy@critchley.biz", envoy_mail_spool.store_messages),
        #("envoy_test@critchley.biz", envoy_responses_mail_spool.store_messages),

        #("john.wellfound@critchley.biz", wf_mail_spool.store_messages),

        #("john-medium@critchley.biz", mail_spool.store_messages), # medium.com
        # ("john.boots_advantage_card@critchley.biz", mail_spool.store_messages), # boots
        #("john.amazon.com@critchley.biz", mail_spool.store_messages),
        #("john.tr@critchley.biz", mail_spool.store_messages), # Tech Republic
        #("john.q@critchley.biz", mail_spool.store_messages),
        #("john.___@critchley.biz", mail_spool.store_messages),
    ]
def do_processing(new_emails, mail_db=None, meta_db_file = os.path.expanduser("~/.email3.meta.gdbm")):
    assert isinstance(meta_db_file, (str, bytes, os.PathLike)), f"meta_db_file, is a {type(meta_db_file)} not str, bytes or os.PathLike."
    foo={}
    deletes=set()
    print("Processing new emails:")
    print(*(x[0].decode('utf-8') for x in new_emails), sep=',')
    
    with gdata.gdata(gdbm_file=meta_db_file, mode=mode) as metadb:
        for uidl, email_bin in new_emails:
            msg=email.message_from_bytes(_norm(email_bin))
            To=msg['To']
            try:
                parsed_to = scanmailheaders.parse_email_addresses(To)
            except TypeError as e:
                frm = msg.get('From')
                subj = msg.get('Subject')
                dt = msg.get('Date')
                mid = msg.get('Message-ID')
                print(
                    f"ERROR parsing To header (uidl={uidl!r}): {e}; "
                    f"To={To!r} From={frm!r} Subject={subj!r} Date={dt!r} Message-ID={mid!r}"
                )
                foo.setdefault(None, []).append((uidl, msg))
                continue
            #print('To:', To)
            to_addresses=[ address for address, safe in parsed_to if bool(safe)]
            for addr in to_addresses:
                foo.setdefault(addr, []).append((uidl,msg))
    print(json.dumps(sorted([(to, len(refs)) for to, refs in foo.items()], key=lambda x:x[1])))
    for email_match, mail_func in map:
        print(f"Processing {email_match}:")
        try:
            dels=mail_func(foo.get(email_match, []))
            print('Dels:', dels)
            deletes.update(dels) # still call even if new IDs, for old mail expiration etc
        except Exception as e:
            print(type(email_match))
            print(f"Error processing emails for {email_match}: {e}")
            print(traceback.format_exc())
#            import pdb
#            pdb.set_trace()

    return deletes
