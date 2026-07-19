# Security — Google API Privacy Requirements

Google has specific rules for apps that access Gmail, Calendar, and Drive.
Violating these can result in your OAuth consent screen being revoked.

---

## Google's Limited Use Requirements

Apps that access Gmail data must comply with Google's
**Limited Use Requirements** (required for Gmail scopes).

| Requirement | How Kora complies |
|---|---|
| Only use data for the purpose the user consented to | Gmail data used solely for client communication intelligence. Calendar for meeting awareness. Drive for document processing. |
| Do not transfer data to others unless necessary for the app to function | Data goes to Gemini (Google's own AI) for processing. No other third party receives email content. |
| Do not use data for advertising | Kora has no advertising. Never. |
| Do not use data to train AI models | Vertex AI/Gemini API does not use customer prompt data for training. This is in Google's API ToS. |
| Allow users to revoke access | Disconnect button in Settings. Calls Google's revocation endpoint + deletes all stored tokens and cached data. |
| Display a privacy policy that discloses Google API data usage | Privacy policy at /privacy explicitly states what Google data is accessed and how. |
| Handle data securely | OAuth tokens encrypted with Fernet. No plaintext storage. TLS in transit. |

---

## Technical enforcement

### 1. Gmail filtering — only read client-related threads

```python
# BEFORE reading any Gmail thread:
# 1. Get the list of known client emails
client_emails = [c["email"] for c in store.list_clients(user_id) if c.get("email")]

# 2. Build the Gmail search query using ONLY client emails
# NEVER use a broad query like "in:inbox" or "is:unread"
query = " OR ".join(f"from:{email} OR to:{email}" for email in client_emails)

# 3. If no client emails exist, DO NOT read any Gmail threads
if not client_emails:
    return []  # nothing to read

# This ensures: personal emails, newsletters, marketing = never touched
```

### 2. Drive scoping — only Kora folder + Meet transcripts

```python
# BEFORE listing any Drive files:
# 1. Only list files in the user's designated Kora folder
if kora_folder_id:
    query = f"'{kora_folder_id}' in parents and trashed = false"
    # This is scoped to ONE folder — cannot access anything else

# 2. For Meet transcripts: search by name pattern, not broad scan
transcript_query = (
    "(name contains 'transcript' or name contains 'Transcript') "
    "and trashed = false"
)
# This finds transcript files but does NOT browse the full Drive tree
```

### 3. No permanent storage of raw email content

```python
# email_intel_cache stores ONLY:
# - summary (AI-generated, not the raw email text)
# - sentiment (one word)
# - action_needed (boolean)
# - commitments_pending (structured extraction, not raw text)

# It does NOT store:
# - Full email body text
# - Email HTML content
# - Attachment content
# - Email headers beyond From/Date

# The raw email snippet (200 chars) is used for AI processing
# in memory during the analysis call, then discarded.
# It is NEVER written to the database.
```

### 4. Token security

```python
# Tokens are:
# - Encrypted with Fernet before DB write (TOKEN_ENCRYPTION_KEY)
# - Decrypted only in memory for API calls
# - Never logged (not in print(), not in Sentry, not in agent_logs)
# - Never sent to the frontend (backend-only access)
# - Revoked on disconnect (POST to Google's revocation endpoint)
# - Deleted from DB on disconnect (not just marked inactive)

# The TOKEN_ENCRYPTION_KEY is:
# - Generated once with Fernet.generate_key()
# - Stored in environment variables only
# - Never committed to git
# - Never logged or exposed
# - If compromised: rotate key + re-encrypt all existing tokens
```

### 5. Data deletion on Google disconnect

```python
# When user clicks "Disconnect Google":
# 1. Revoke access token with Google
# 2. DELETE google_connections row (removes encrypted tokens)
# 3. DELETE all email_intel_cache rows for this user
# 4. DELETE all drive_doc_cache rows for this user
# 5. UPDATE users SET google_connected = false, google_email = null
# 6. Meetings and client_notes from Google sources remain
#    (they are the user's business data, not Google's)
```

---

## What to show in the privacy consent UI (before OAuth)

```
Kora needs access to your Google account to provide intelligent
business management. Here's exactly what happens:

GMAIL
✓ Kora reads email threads between you and your clients
✗ Kora never reads personal emails, newsletters, or subscriptions
✗ Kora never stores the full text of your emails
✓ Email summaries are processed by Google's AI (Gemini)
✓ You can disconnect at any time — all cached email data is deleted immediately

CALENDAR
✓ Kora reads your upcoming events to show in the morning briefing
✗ Kora never reads event descriptions or notes
✓ Kora can create calendar events (only when you approve)

DRIVE
✓ Kora reads files in your "Kora" folder (you control what goes here)
✓ Kora reads Google Meet transcripts automatically
✗ Kora never browses your entire Drive
✗ Kora never modifies or deletes your Drive files

Your data is never sold, never used for advertising, and never used
to train AI models. See our Privacy Policy for full details.

[Connect Google]    [Cancel]
```
