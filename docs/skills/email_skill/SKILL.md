---
name: kora-google-butler
description: >
  Build the Kora Butler Google Workspace integration — the intelligence layer that
  connects Gmail, Calendar, and Drive to the Butler so it can observe the user's
  business without being told. Use this skill for: Google OAuth flow, Gmail thread
  reading and analysis, Drive document ingestion and classification, Calendar awareness,
  meeting transcript processing, email drafting and sending on behalf of user,
  invoice creation from email context, contract detection from Drive, morning briefing
  synthesis from all sources, and the HITL approval queue for all outbound actions.
  Triggers on: "connect Gmail", "read emails", "Drive documents", "email on behalf",
  "client emails", "transcripts", "Google Workspace", "email intelligence",
  "communication history", "schedule meeting", "calendar", "Butler Google",
  "meeting notes", "MOM", "send email from Gmail", "Kora folder".
---

# Kora Butler — Google Workspace Intelligence

> "The Butler reads your Gmail, watches your calendar, and understands your Drive.
>  It knows your business the way you do — without you having to tell it anything."

This is the **single consolidated skill** for all Google integration in Kora.
It replaces and supersedes `kora-comms-skill/` and `kora-butler-comms/`.
If Claude Code encounters those older packages, ignore them — this file is canonical.

Read the reference files in this order:
1. `references/oauth.md`          — Google OAuth setup, scopes, token encryption, consent
2. `references/schema.md`         — ALL new DB tables and column additions (definitive)
3. `references/gmail-intel.md`    — Gmail thread reading, client matching, AI analysis
4. `references/drive-intel.md`    — Drive ingestion: Kora folder, transcripts, classification
5. `references/calendar-intel.md` — Calendar event reading, client matching, scheduling
6. `references/butler-brain.md`   — unified gather_full_state() + ONE Gemini briefing call
7. `references/actions.md`        — email send, calendar create, invoice from email, HITL queue
8. `references/meeting-agent.md`  — transcript processing, MOM extraction, action items

---

## 1. Architecture summary

```
LAYER 1 — Sources:       Gmail API · Calendar API · Drive API (+ Docs API for export)
LAYER 2 — Ingestion:     gmail_intel.py · calendar_intel.py · drive_intel.py (daily workers)
LAYER 3 — Cache + DB:    email_intel_cache · drive_doc_cache · meetings · clients
LAYER 4 — Butler brain:  gather_full_state() → ONE Gemini call → briefing JSON
LAYER 5 — Outputs:       morning briefing · client health · alerts · meeting notes
LAYER 6 — Action queue:  manager_tasks (propose → user approves → execute)
```

Key principle: Layers 1–3 run in background workers (daily at 07:00 UTC).
Layer 4 reads from cache only — never calls Google APIs at briefing time.
Layer 6 never executes outbound actions without user approval.

---

## 2. Google APIs required (all enabled in GCP Console)

```
Gmail API              — read threads, send on behalf
Google Calendar API    — read events, create invites with Meet links
Google Drive API       — list files, download content
Google Docs API        — required for files.export() on native Google Docs
                         (no new OAuth scope needed — Drive scopes cover it)
```

The Docs API must be enabled because Drive's files.export() call for native
Google Docs internally routes through the Docs API. Without it enabled,
export calls return 403 on some account types. It adds zero cost and no new scope.

---

## 3. OAuth scopes (exact list)

```python
SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/drive.readonly",
    # For production (avoid CASA audit): replace drive.readonly with:
    # "https://www.googleapis.com/auth/drive.file",
]
```

Google People API is NOT needed. User profile comes from `userinfo.email` + `userinfo.profile`.
Google Sheets API is NOT needed.

---

## 4. Absolute rules (never violate)

1. **Read only client-related email.** Before reading any Gmail thread, verify
   at least one participant's email matches a client in `clients` table.
   Never read threads with no client match.

2. **Drive reads are scoped.** Only read files from the user's designated
   "Kora" folder (`google_connections.kora_folder_id`) and auto-saved
   Google Meet transcripts. Never browse the full Drive tree.

3. **All outbound actions require HITL approval.** Every email draft, calendar
   event, and invoice created from email context goes into `manager_tasks`
   with `status='proposed'`. Nothing sends without the user clicking Approve.

4. **Tokens encrypted at rest.** `google_connections.access_token_enc` and
   `refresh_token_enc` are Fernet-encrypted. Never store plaintext tokens.
   Never log tokens. Never expose tokens to the frontend.

5. **AI processing disclosure.** Email and document content sent to Gemini.
   User consented explicitly (timestamp in `google_connections.consent_given_at`).
   Never log email content to Sentry. Never include email body in error reports.

6. **Cache aggressively.** `email_intel_cache` and `drive_doc_cache` prevent
   re-processing unchanged data. Never re-process a Gmail thread unless it
   has new messages. Never re-process a Drive file unless it was modified.

7. **All intelligence logged to agent_logs.** `agent_type` values:
   `butler_gmail`, `butler_drive`, `butler_calendar`, `meeting_agent`.
   Every AI call produces one log row.

8. **Graceful degradation.** If Google is not connected, the Butler runs in
   "Told mode" only. Every feature works without Google. Morning briefing,
   invoices, contracts, follow-ups all function with zero Google connection.

9. **GDPR deletion includes Google cache.** When a user deletes their account,
   clear `email_intel_cache`, `drive_doc_cache`, and `google_connections`
   before deleting the user record.

10. **All Gemini calls through `vertex_ai.py`.** Use `generate_with_retry()`
    and `getGeminiForAgent()`. Never call Gemini directly. Never use
    OpenAI or Anthropic SDK.

---

## 5. Build order

**Phase 1 — OAuth + privacy consent (Days 1–2)**
Read `references/oauth.md`.

**Phase 2 — Schema migrations (Day 3)**
Read `references/schema.md`. Apply all migrations in order.

**Phase 3 — Gmail intelligence (Days 4–8)**
Read `references/gmail-intel.md`.

**Phase 4 — Drive intelligence (Days 9–13)**
Read `references/drive-intel.md`.

**Phase 5 — Calendar intelligence (Days 14–16)**
Read `references/calendar-intel.md`.

**Phase 6 — Meeting agent (Days 17–20)**
Read `references/meeting-agent.md`.

**Phase 7 — Butler brain synthesis (Days 21–24)**
Read `references/butler-brain.md`.

**Phase 8 — Action execution (Days 25–28)**
Read `references/actions.md`.

---

## 6. File layout (new backend files)

```
backend/app/
  routers/
    auth_google.py      — OAuth connect/callback/disconnect
    gmail_intel.py      — email intel endpoints + draft triggers
    meetings.py         — meeting CRUD + transcript upload
  services/
    token_encryption.py — Fernet encrypt/decrypt for OAuth tokens
    google_auth.py      — get_user_credentials() with auto-refresh
    gmail_intel.py      — thread fetching, filtering, AI analysis, caching
    gmail_draft.py      — email draft generation, queue for HITL
    gmail_agent.py      — queue_gmail_send() + execute_gmail_send()
    drive_intel.py      — Kora folder scan, file classification, routing
    calendar_intel.py   — today's events, client matching, availability
    calendar_agent.py   — queue_calendar_event() + execute_calendar_event()
    meeting_agent.py    — transcript parsing, MOM extraction, action items

workers/
  butler_google_sync.py — 07:00 UTC daily: gmail + drive + calendar sync
```

---

## 7. Environment variables

```bash
# Google OAuth (same GCP project as Vertex AI)
GOOGLE_OAUTH_CLIENT_ID=
GOOGLE_OAUTH_CLIENT_SECRET=
GOOGLE_OAUTH_REDIRECT_URI=http://localhost:3000/api/auth/google/callback

# Token encryption (generate once, never change after first user connects)
# python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
TOKEN_ENCRYPTION_KEY=

# Tuning
GMAIL_BATCH_SIZE=20              # max threads per client per sync
DRIVE_KORA_FOLDER_NAME=Kora     # name of folder Butler watches
```

---

## 8. Pip dependencies (add to requirements.txt)

```
google-auth>=2.28.0
google-auth-oauthlib>=1.2.0
google-auth-httplib2>=0.2.0
google-api-python-client>=2.118.0
cryptography>=42.0.0
pdfplumber>=0.10.0
python-docx>=1.1.0
```

---

## 9. Cost controls

| Operation | Frequency | Gemini cost |
|---|---|---|
| Gmail thread analysis (per thread) | Daily, new threads only | ~$0.02 |
| Drive file classification | Per new file | ~$0.01 |
| Drive transcript → MOM | Per meeting | ~$0.03 |
| Morning briefing synthesis | Daily, 1 call/user | ~$0.02 |
| Email draft generation | On demand | ~$0.01 |

At 50 users: ~$5–8/month. Cache all results. Re-process only on change.
