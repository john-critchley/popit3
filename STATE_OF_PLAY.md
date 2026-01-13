# State of play (13 Jan 2026)

This note is a snapshot of where the codebase is today, with emphasis on the POP3 sync + storage model, and why `UIDL` vs `Message-ID` matters for “easy lookup” of a stored email.

## 1) What the system does today (high level)

- `popit3.py` connects to Outlook POP3 (XOAUTH2), lists server messages by POP3 `UIDL`, downloads any unseen messages, stores raw bytes into a local GNU dbm (via `gdata.gdata_raw`), then hands newly-downloaded messages to `process_emails.do_processing()`.
- `process_emails.py` parses each message (stdlib `email.message_from_bytes`) and “routes” it by `To:` address to per-mailbox handlers.
  - David Lloyd: `MyDavidLloydSchedule.process_dl_mails`
  - Jobserve: `newparser_jobserve.process_js_mails`
  - Everything else: stored into a maildir (and WebDAV) via `mailspool.MailSpool`

## 2) Current storage: what’s in gdbm, keyed by what

### 2.1 `~/.email3.mail.gdbm` (raw mail store)

- **File:** `~/.email3.mail.gdbm` (default `DEFAULT_DBFILE` in `popit3.py`)
- **Key:** POP3 `UIDL` (bytes)
- **Value:** raw message bytes (`bytes`) exactly as fetched from POP3 (as stored by `maildb[uidl] = raw`)

This store is effectively: `UIDL -> raw_rfc822_bytes`.

### 2.2 `~/.email3.meta.gdbm` (metadata store)

- **File:** `~/.email3.meta.gdbm` (used in `process_emails.do_processing`)
- **Key/value:** currently used as a generic metadata db, but in the code shown it’s not (yet) being used to build an index from `Message-ID` to `UIDL`.

### 2.3 Other gdbm stores (domain-specific)

These are separate “processed” databases, and they show a different design choice: **use `Message-ID` as primary key**.

- Jobserve processing (`newparser_jobserve.py`):
  - `~/.jobserve.gdbm` is keyed by `Message-ID` and stores structured metadata (job type, parsed job, etc.).
- David Lloyd processing (`MyDavidLloydSchedule.py`):
  - `~/.mail/.booking_map2.gdbm` maps booking reference -> list of `[Message-ID, UIDL]` pairs.
  - `~/.mail/.booksings_db2.gdbm` stores booking records keyed by booking reference.

So: the raw-mail database is `UIDL`-keyed, while at least one downstream processor (Jobserve) already thinks of `Message-ID` as the “primary key” for processed artifacts.

## 3) UIDL vs Message-ID: what they are and why it matters

### 3.1 POP3 UIDL

- `UIDL` is a POP3 server-provided “unique-id listing”.
- **Intended property:** stable across sessions **for as long as the message remains on that server/mailbox**.
- **Not guaranteed forever:** a server migration/reindex/restore can change UIDLs even for the “same” message.

Practical implication:
- Great as a fast incremental-sync key (don’t re-download the same message).
- Not ideal as a long-term, global identifier you can rely on for years.

### 3.2 RFC 5322 Message-ID

- `Message-ID` is an email header usually set by the sending system.
- Usually stable and globally unique-ish.
- Caveats:
  - Some messages might not have it.
  - Some systems can generate duplicates.
  - You can’t know it without parsing message headers (i.e., you need the bytes first).

Practical implication:
- Good as an application-level identifier.
- But you can’t use it as your *primary* download key, because POP3 doesn’t let you request “message with Message-ID X”; POP3 gives you message numbers and UIDLs.

## 4) The core tension: “easy lookup by Message-ID” vs “don’t scan”

### 4.1 Why lookup-by-Message-ID currently requires scanning

Because `~/.email3.mail.gdbm` is keyed by `UIDL`, given only a `Message-ID` there is no direct key lookup.

Today, to answer “give me the raw email for Message-ID `<…>`” you must either:

1) **Scan** the whole `UIDL -> raw_bytes` database, parse headers until you find a match, or
2) Have (or build) an **index** that maps `Message-ID -> UIDL`.

### 4.2 “But indexing needs parsing too”

Correct: to populate `Message-ID -> UIDL`, you must parse headers at least once.

However, the important optimization is *when* you pay that cost:

- Bad: pay it at lookup time by scanning everything repeatedly.
- Good: pay it at ingest time (when you already fetched the message), and store an index entry.

This does **not** require a major rewrite of POP3 downloading, but it *does* add a deliberate “index build/update” step in the POP3 ingest pipeline.

## 5) Current operational issue we hit: BOM-prefixed stored messages

We found at least one stored message in `~/.email3.mail.gdbm` that begins with a UTF‑8 BOM (`0xEFBBBF`).

Effect:
- If you feed the BOM-prefixed bytes directly to `email.message_from_bytes`, the parser can behave oddly (e.g., headers appear missing/None), because those bytes appear before the RFC 5322 header section.

Implication:
- Any “Message-ID indexing” should normalize input bytes first (e.g., strip BOM if present) before parsing headers.

## 6) What we likely want to have (storage/indexes)

### 6.1 Keep the raw store as-is

Keep:
- `~/.email3.mail.gdbm`: `UIDL -> raw_bytes`

Reason:
- It’s the natural POP3 incremental sync key.

### 6.2 Add a dedicated Message-ID index db

Add:
- `~/.email3.msgid.gdbm`: `normalized_message_id -> uidl`

Where `normalized_message_id` is something like:
- Lowercased, stripped whitespace
- Ensure it’s wrapped in `<…>` consistently

Update policy:
- On ingest of a message (when we store `maildb[uidl] = raw`), parse only headers, extract Message-ID, and store `msgid_index[msg_id] = uidl`.
- If the same Message-ID arrives again with a different UIDL (rare): either overwrite or keep a small list.

This gives you **O(1)** lookup by Message-ID without scanning.

### 6.3 Optional reverse index

Optionally also store:
- `~/.email3.uidl.gdbm`: `uidl -> message_id`

This can help debugging and provides quick “what is this UIDL?” introspection.

### 6.4 Consider a header-only cache

If you want to avoid repeatedly parsing raw bytes just to get common headers:
- `~/.email3.headers.gdbm`: `uidl -> {Message-ID, Date, Subject, From, To, …}`

This is strictly an optimization convenience.

## 7) What objects/data structures we might want in code

This is about code clarity more than “new features”.

### 7.1 A normalized message identity

A small helper concept:

- `MessageKey`
  - `uidl: bytes | None`
  - `message_id: str | None` (normalized)

This acknowledges reality: sometimes you have UIDL (POP3 world), sometimes you have Message-ID (email world).

### 7.2 A message record

- `RawMessage`
  - `uidl: bytes`
  - `raw: bytes`
  - `headers: email.message.Message` (or a dict of selected headers)

### 7.3 Storage facades

Wrap gdbm access behind small “repositories”:

- `RawMailStore` (`uidl -> raw_bytes`)
- `MessageIdIndex` (`message_id -> uidl`)

So higher-level code can do:

- `uidl = msgid_index.lookup(msgid)`
- `raw = raw_store.get(uidl)`

…without ever scanning.

## 8) What this means for rewriting

- The POP3 sync logic itself (download-by-UIDL) is fine.
- The missing piece for “easy lookup by Message-ID” is an **index** built at ingest time.
- There is a small but important correctness requirement: **strip BOM before parsing headers**.

So this is not necessarily a “fairly major rewrite”, but it is a meaningful architectural decision: treating raw storage and lookup indexes as first-class parts of the ingestion pipeline.

## 9) Where we were in the debugging thread (non-POP3)

- The David Lloyd processing crashed because some email kinds were classified as `unknown`, and `MyDavidLloydSchedule.process_dl_mails` asserts kinds are only `booking|cancellation|booking_update`.
- Separately, we discovered BOM-prefixed stored messages while trying to locate a specific `Message-ID`.

Those are distinct issues, but the BOM discovery directly impacts any future Message-ID indexing.
