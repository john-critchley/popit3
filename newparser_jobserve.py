if __name__ != "__main__": print("Module:", __name__)
import gdata
import os
import pdb
import email
import email.utils
import email.header
import datetime
import random
import traceback
import json
import re
import argparse
import zlib
import box
import js_alert_parser # parse_jobserve_alert
import yaml
import openai

#import pdb

import js_email
#import analyze_jobs_openai

KEY_PATH = "~/py/popit3/.openai"
CV_PATH = os.environ.get('CV_PATH', "~/Downloads/cv_llm_optimized.md")

MODEL='gpt-4o-mini'
SYSTEM_CONTENT = (
    "You are a career assistant helping with job application suitability analysis. "
    "You have expertise in matching CVs to job requirements and providing realistic assessments. "
    "You analyze technical skills, experience relevance, and overall job fit. "
    "BE DISCRIMINATING with scores - use the full 0-10 range and avoid grade inflation. "
    "Respond with clear reasoning and finish with a line that exactly matches:\n"
    "Score: N\n"
)

DATABASE_FILENAME = ('~/.jobserve.gdbm')

def decode_header_value(header_value):
    """Decode RFC 2047 encoded header values"""

    return ''.join(
        part
            if encoding is None else
        part.decode(encoding or 'utf-8', errors='replace')
            for part, encoding in 
                 email.header.decode_header(header_value)
    ) if header_value else ""

def classify_job(subj):
    if 'job suggestion' in subj:
        print(f"Processing JOB SUGGESTION: {subj}")
        return 'suggestion'
    elif 'job alert' in subj:
        print(f"Processing JOB ALERT: {subj}")
        return 'alert'
    elif 'Application Confirmation' in subj:
        print(f"Processing APPLICATION CONFIRMATION: {subj}")
        return 'application'
    else:
        print(f"Skipping non-job email: {subj}")
        return None

def process_js_mails(js_emails):
    print('process_js_mails')
    print(f'len js_emails {len(js_emails)}')
    gdbm_path = os.path.join(os.path.expanduser(DATABASE_FILENAME))
    js_gd=gdata.gdata(gdbm_path) # I cleanup at the end
    uids_to_delete=set()
    for uid, msg in js_emails:
        uid=int(uid)
        msg_id=msg['Message-ID']
        print("Mail UID:", uid, "Message:", msg_id)
        if not ( msg_id.startswith('<') and msg_id.endswith('>') ):
            print("Warning - Doesn't have angle brackets - added")
            msg_id=f'<{msg_id}>'
        rec=box.Box(js_gd.get(msg_id, {}))

        if 'Subject' in msg and not 'subject' in rec:
            rec.subject = decode_header_value(msg['Subject'])
        print(f'Subject: {rec.subject}')
        if 'job_type' not in rec:
            rec.job_type=classify_job(rec.subject)
        
        if rec.job_type is None:
            print("Not an automated job notification - marking as unclassified")
            if 'Date' in msg:
                sent_date=email.utils.parsedate_to_datetime(msg['Date'])
                rec.date=sent_date.isoformat()
            rec.unclassified = {}
            js_gd[msg_id]=rec.to_dict()
            print("Stored unclassified email")
            continue
        if 'Date' not in msg:
            print("No date field")
            continue
        if 'date' in rec:
            sent_date=datetime.datetime.fromisoformat(rec.date)
        else:
            sent_date=email.utils.parsedate_to_datetime(msg['Date'])
            rec.date=sent_date.isoformat()
        print('Sent:', sent_date, '/', rec.date)
        age=datetime.datetime.now(datetime.UTC)-sent_date
        if  age>datetime.timedelta(days=7):
            print("Too old - skipping", age)
            uids_to_delete.add(uid)
            if msg_id in js_gd:
                del js_gd[msg_id]
            continue

        for part in msg.walk():
            if part.is_multipart():
                print("Found multipart")
                continue
            cty=part.get_content_type()
            print("Content type:", cty)
            if cty not in ['text/plain', 'text/html']:
                continue
            
            ext='html' if cty[cty.index('/')+1:]=='html' else 'txt'
            sj=str().join(ch for ch in rec.subject if ch not in '/')
            fn=f'text/{sj} {zlib.crc32(msg_id.encode('utf-32'))}.{ext}'
            # XXX If the file doesn't already exist or has a different time
            if not os.path.exists(fn) or 'charset' not in rec:
                print("Writing:", fn)
                payload = part.get_payload(decode=True)
                with open(fn, 'wb') as fd:
                    fd.write(payload)
                if sent_date and isinstance(sent_date, datetime.datetime):
                    mod_timestamp = sent_date.timestamp()
                    os.utime(fn, (mod_timestamp, mod_timestamp))    
                if ext=='txt':
                    continue # Later we will do something different maybe
                rec.charset=part.get_content_charset() or 'utf-8'
            else:
                with open(fn, 'rb') as fd:
                    payload=fd.read()
                
            html_content = payload.decode(rec.charset)
            
            # Handle application confirmations separately
            if rec.job_type == "application":
                import js_application_parser
                if 'parsed_application' not in rec:
                    rec.parsed_application = js_application_parser.parse_jobserve_application_confirmation(html_content)
                    print("Parsed application:", rec.parsed_application)
                
                # Store ONLY in separate applications database, not in main jobs database
                app_gdbm_path = os.path.expanduser('~/.jobserve_applications.gdbm')
                app_gd = gdata.gdata(app_gdbm_path)
                app_gd[msg_id] = dict(rec)
                app_gd.close()
                print("Stored application confirmation")
                continue  # Don't store in main jobs database
            
            # Handle job suggestions and alerts
            if 'parsed_job' not in rec:
                if rec.job_type =="suggestion":
                    rec.parsed_job = js_email.parse_jobserve_email_part(html_content)
                elif rec.job_type =="alert":
                    rec.parsed_job = js_alert_parser.parse_jobserve_alert(html_content)
                else:
                    print("Job type not suggestion nor alert but",rec.job_type)
                    continue
                print("Parsed:", rec.parsed_job)
                if 'job_url' not in rec.parsed_job:
                    print("rec.parsed_job", rec.job_type, "is missing job_url")
                else:
                    print("job_url is", rec.parsed_job.job_url)
            if 'scored_job' not in rec:
                if 'cv' not in vars():
                    cv_file = os.path.expanduser(CV_PATH)
                    with open(cv_file, 'r') as fd:
                        cv = fd.read()
                if 'client' not in vars():
                    with open(os.path.expanduser(KEY_PATH + ".yaml"), "r") as fd:
                        client_params = yaml.safe_load(fd.read())
                    client = openai.OpenAI(**client_params)

                # Define the schema for the LLM output
                schema_instruction = (
                    "Analyze how well this CV matches the job description. "
                    "Respond in JSON with two fields: 'score' (integer 0-10, be discriminating) and 'reason' (string). "
                    "In 'reason', provide a detailed explanation (at least 120-200 words) including: "
                    "key skill matches, experience gaps, seniority fit, domain relevance, and any blockers (e.g., location, clearance). "
                    "Use clear sentences (no bullet lists) to keep it readable. "
                    "Example: {\"score\": 7, \"reason\": \"Strong Python and data experience, but limited MLOps...\"} "
                )
                chat_completion = client.chat.completions.create(
                    messages=[
                        {"role": "system", "content": SYSTEM_CONTENT},
                        {"role": "user", "content": '\n'.join((
                            schema_instruction,
                            "Job Details:", rec.parsed_job['description'],
                            "CV:", cv
                        ))}
                    ],
                    model=MODEL,
                    temperature=0.3,
                    response_format={"type": "json_object"},
                    max_tokens=600
                )
                response_json = chat_completion.choices[0].message.content
                print(f"Response (JSON):", response_json)
                rec.scored_job = response_json

            if 'score' not in rec:
                try:
                    scored = json.loads(rec.scored_job)
                    rec.score = int(scored.get('score'))
                    rec.score_reason = scored.get('reason', '')
                    print('score added:', rec.score)
                    print('score reason:', rec.score_reason)
                except json.JSONDecodeError as e:
                    import traceback
                    print("Failed to parse score from JSON response:", e)
                    print("Raw response:", rec.scored_job)
                    traceback.print_exc()
            else:
                print('score found:', rec.score)
        js_gd[msg_id]=rec.to_dict()
        print("/\\"*20)
    return uids_to_delete

            

#def main(js_emails, dbfile='~/.email3.mail.gdbm', verbose=True):
#    with gdata.gdata(os.path.expanduser(dbfile), mode='r') as emaildb:
#        if not js_emails:
#            js_emails=emaildb.keys()
#        iemails=[(k, email.message_from_bytes(emaildb[k])) for k in js_emails]
#        return process_js_mails(iemails)
#
#if __name__=="__main__":
#    p = argparse.ArgumentParser(description="Parse a jobserve email and AI it" )
#    p.add_argument("ids", help=f"Message-IDs")
#    p.add_argument("--dbfile", help=f"Path to gdbm file (default {DATABASE_FILENAME})")
#    p.add_argument("--verbose", action="store_true", help="More verbose debugging")
#    p.add_argument("--no-verbose", dest="verbose", action="store_false", help="Disable verbose")
#
#    #p.add_argument("--reprocess", action="store_true", help="Reprocess mails already seen")
#    #p.add_argument("--no-reprocess", dest="reprocess", action="store_false", help="Disable reprocess")
#    p.set_defaults(show=None, reprocess=None)
#    ns=p.parse_args()
#    args=ns.args
#    kwargs = {k: v for k, v in vars(ns).items() if v is not None and v!='ids'}
#    print(main(*args, **kwargs))
